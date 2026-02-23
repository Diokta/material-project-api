from mp_api.client import MPRester
import pandas as pd
import logging
import time
from tqdm import tqdm
import os
import shutil
import math

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default API Key
DEFAULT_API_KEY = "pXWZG9u9gI4oST0zIxDuU6qhA8eHCU26"
API_KEY = os.environ.get("MP_API_KEY", DEFAULT_API_KEY)

WORKING_FILE = "materials_data_working.csv"
FINAL_OUTPUT_FILE = "materials_data.csv"
CHUNK_SIZE = 1000

def fetch_materials():
    """
    Fetches material data from the Materials Project API and saves it to a CSV file.
    Merges data from Summary and Elasticity endpoints.
    """
    try:
        logger.info("Connecting to Materials Project API...")

        existing_ids = set()

        if os.path.exists(WORKING_FILE):
            logger.info(f"Reading existing data from {WORKING_FILE}...")
            try:
                df_existing = pd.read_csv(WORKING_FILE, usecols=["Material ID"])
                existing_ids = set(df_existing["Material ID"].astype(str))
                logger.info(f"Found {len(existing_ids)} existing materials.")
            except Exception as e:
                logger.warning(f"Could not read existing file: {e}. Starting fresh.")
        else:
            headers = [
                "Material ID", "Formula", "Energy above Hull", "Formation Energy",
                "Predicted Stable", "Elastic Constants",
                "Bulk Modulus Voigt", "Bulk Modulus Reuss", "Bulk Modulus VRH",
                "Shear Modulus Voigt", "Shear Modulus Reuss", "Shear Modulus VRH",
                "Youngs Modulus", "Elastic Anisotropy", "Density", "Volume",
                "Crystal System", "Band Gap", "Is Metal", "Sites"
            ]
            pd.DataFrame(columns=headers).to_csv(WORKING_FILE, index=False)

        with MPRester(API_KEY) as mpr:
            total_fetched = 0

            # Summary fields
            summary_fields = [
                "material_id", "formula_pretty", "energy_above_hull",
                "formation_energy_per_atom", "is_stable", "volume",
                "density", "band_gap", "is_metal", "nsites",
                "symmetry", "universal_anisotropy", "bulk_modulus", "shear_modulus"
            ]

            # Elasticity fields
            elasticity_fields = ["material_id", "elastic_tensor"]

            for n in range(1, 13):
                logger.info(f"Fetching materials with {n} elements...")

                try:
                    # Fetch IDs only first
                    docs = mpr.materials.summary.search(
                        num_elements=(n, n),
                        fields=["material_id"]
                    )

                    if not docs:
                        continue

                    all_ids = [str(doc.material_id) for doc in docs]
                    new_ids = [mid for mid in all_ids if mid not in existing_ids]

                    if not new_ids:
                        logger.info(f"All {len(all_ids)} materials with {n} elements already fetched.")
                        continue

                    logger.info(f"Found {len(all_ids)} materials, {len(new_ids)} new to fetch.")

                    for i in tqdm(range(0, len(new_ids), CHUNK_SIZE), desc=f"Processing {n}-element materials"):
                        chunk_ids = new_ids[i:i + CHUNK_SIZE]

                        try:
                            # 1. Fetch Summary Data
                            summary_docs = mpr.materials.summary.search(
                                material_ids=chunk_ids,
                                fields=summary_fields
                            )

                            # 2. Fetch Elasticity Data for these IDs
                            # Elasticity endpoint search by material_ids
                            # Note: Not all materials have elasticity data
                            elasticity_map = {}
                            try:
                                elasticity_docs = mpr.materials.elasticity.search(
                                    material_ids=chunk_ids,
                                    fields=elasticity_fields
                                )
                                for edoc in elasticity_docs:
                                    # store elastic_tensor. It might be an object or list.
                                    # If object, try to convert to list/dict str
                                    tensor = edoc.elastic_tensor
                                    if hasattr(tensor, "voigt"):
                                        # pymatgen tensor object?
                                        tensor = tensor.voigt.tolist()
                                    elasticity_map[str(edoc.material_id)] = tensor
                            except Exception as e:
                                logger.warning(f"Error fetching elasticity for chunk: {e}")
                                # Continue without elasticity data

                            data = []
                            for doc in summary_docs:
                                mid = str(doc.material_id)

                                # Extract elasticity from summary
                                k_voigt = None
                                k_reuss = None
                                k_vrh = None
                                g_voigt = None
                                g_reuss = None
                                g_vrh = None

                                if doc.bulk_modulus is not None:
                                    if isinstance(doc.bulk_modulus, dict):
                                        k_voigt = doc.bulk_modulus.get('voigt')
                                        k_reuss = doc.bulk_modulus.get('reuss')
                                        k_vrh = doc.bulk_modulus.get('vrh')
                                    elif isinstance(doc.bulk_modulus, (int, float)):
                                        k_vrh = doc.bulk_modulus

                                if doc.shear_modulus is not None:
                                    if isinstance(doc.shear_modulus, dict):
                                        g_voigt = doc.shear_modulus.get('voigt')
                                        g_reuss = doc.shear_modulus.get('reuss')
                                        g_vrh = doc.shear_modulus.get('vrh')
                                    elif isinstance(doc.shear_modulus, (int, float)):
                                        g_vrh = doc.shear_modulus

                                # Calculate Young's Modulus (Hill average assumption usually)
                                # E = 9KG / (3K + G)
                                youngs = None
                                if k_vrh and g_vrh:
                                    if (3 * k_vrh + g_vrh) != 0:
                                        youngs = (9 * k_vrh * g_vrh) / (3 * k_vrh + g_vrh)

                                # Crystal system
                                crystal_sys = None
                                if doc.symmetry:
                                    # symmetry is an object
                                    if hasattr(doc.symmetry, 'crystal_system'):
                                         crystal_sys = str(doc.symmetry.crystal_system)
                                    else:
                                         crystal_sys = str(doc.symmetry) # Fallback

                                # Elastic Tensor
                                e_tensor = elasticity_map.get(mid)

                                entry = {
                                    "Material ID": mid,
                                    "Formula": doc.formula_pretty,
                                    "Energy above Hull": doc.energy_above_hull,
                                    "Formation Energy": doc.formation_energy_per_atom,
                                    "Predicted Stable": doc.is_stable,
                                    "Elastic Constants": str(e_tensor) if e_tensor else None,
                                    "Bulk Modulus Voigt": k_voigt,
                                    "Bulk Modulus Reuss": k_reuss,
                                    "Bulk Modulus VRH": k_vrh,
                                    "Shear Modulus Voigt": g_voigt,
                                    "Shear Modulus Reuss": g_reuss,
                                    "Shear Modulus VRH": g_vrh,
                                    "Youngs Modulus": youngs,
                                    "Elastic Anisotropy": doc.universal_anisotropy,
                                    "Density": doc.density,
                                    "Volume": doc.volume,
                                    "Crystal System": crystal_sys,
                                    "Band Gap": doc.band_gap,
                                    "Is Metal": doc.is_metal,
                                    "Sites": doc.nsites
                                }
                                data.append(entry)

                            if data:
                                df = pd.DataFrame(data)
                                df.to_csv(WORKING_FILE, mode='a', header=False, index=False)
                                total_fetched += len(data)

                        except Exception as e:
                            logger.error(f"Error fetching chunk {i // CHUNK_SIZE} for n={n}: {e}")

                except Exception as e:
                    logger.error(f"Error processing n={n}: {e}")

            logger.info(f"Done fetching. Total fetched in this run: {total_fetched}.")

            finalize_output()

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)

def finalize_output():
    """Reads the working file and saves the final output without Material ID."""
    logger.info(f"Creating final output file {FINAL_OUTPUT_FILE}...")
    try:
        if os.path.exists(WORKING_FILE):
            df = pd.read_csv(WORKING_FILE)

            columns = [
                "Material ID", "Formula", "Energy above Hull", "Formation Energy",
                "Predicted Stable", "Elastic Constants",
                "Bulk Modulus Voigt", "Bulk Modulus Reuss", "Bulk Modulus VRH",
                "Shear Modulus Voigt", "Shear Modulus Reuss", "Shear Modulus VRH",
                "Youngs Modulus", "Elastic Anisotropy", "Density", "Volume",
                "Crystal System", "Band Gap", "Is Metal", "Sites"
            ]

            # The user requested specific fields. "material id" was requested this time!
            # "- material id" ...

            if all(col in df.columns for col in columns):
                df_final = df[columns]
                df_final.to_csv(FINAL_OUTPUT_FILE, index=False)
                logger.info(f"Final data saved to {FINAL_OUTPUT_FILE}")
            else:
                logger.error("Working file missing required columns.")
        else:
            logger.error(f"Working file {WORKING_FILE} not found.")

    except Exception as e:
        logger.error(f"Error finalizing output: {e}")

if __name__ == "__main__":
    fetch_materials()
