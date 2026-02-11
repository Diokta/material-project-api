from mp_api.client import MPRester
import pandas as pd
import logging
import time
from tqdm import tqdm
import os
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default API Key provided in the task description.
# Ideally, this should be set via environment variable MP_API_KEY.
DEFAULT_API_KEY = "pXWZG9u9gI4oST0zIxDuU6qhA8eHCU26"
API_KEY = os.environ.get("MP_API_KEY", DEFAULT_API_KEY)

# We use a working file with ID to allow resuming
WORKING_FILE = "materials_data_working.csv"
FINAL_OUTPUT_FILE = "materials_data.csv"
CHUNK_SIZE = 1000  # Number of materials to fetch per detail request

def fetch_materials():
    """
    Fetches material data from the Materials Project API and saves it to a CSV file.
    Uses batching by number of elements and then chunking IDs to avoid memory issues.
    Resume capability added by checking existing Material IDs in the working file.
    """
    try:
        logger.info("Connecting to Materials Project API...")

        existing_ids = set()

        # Check if working file exists to handle headers and resuming
        if os.path.exists(WORKING_FILE):
            logger.info(f"Reading existing data from {WORKING_FILE}...")
            try:
                # Read only Material ID column to save memory
                df_existing = pd.read_csv(WORKING_FILE, usecols=["Material ID"])
                existing_ids = set(df_existing["Material ID"].astype(str))
                logger.info(f"Found {len(existing_ids)} existing materials.")
            except Exception as e:
                logger.warning(f"Could not read existing file: {e}. Starting fresh.")
                # If reading fails, maybe backup and start fresh?
                # For now, we assume if it fails we might just append or overwrite if empty
        else:
            # Initialize working file with headers including ID
            headers = [
                "Material ID", "Formula", "Sites", "Energy above Hull", "Formation Energy",
                "Predicted Stable", "Volume", "Density", "Band Gap",
                "Bulk Modulus Voigt", "Bulk Modulus Reuss", "Bulk Modulus VRH",
                "Shear Modulus Voigt", "Shear Modulus Reuss", "Shear Modulus VRH"
            ]
            pd.DataFrame(columns=headers).to_csv(WORKING_FILE, index=False)

        with MPRester(API_KEY) as mpr:
            total_fetched = 0

            # Iterate through number of elements (1 to 12)
            # 12 is a safe upper bound for number of elements in a compound
            for n in range(1, 13):
                logger.info(f"Fetching materials with {n} elements...")

                try:
                    # Fetch IDs only for this group using summary endpoint
                    docs = mpr.materials.summary.search(
                        num_elements=(n, n),
                        fields=["material_id"]
                    )

                    if not docs:
                        continue

                    all_ids = [str(doc.material_id) for doc in docs]
                    # Filter out existing IDs
                    new_ids = [mid for mid in all_ids if mid not in existing_ids]

                    if not new_ids:
                        logger.info(f"All {len(all_ids)} materials with {n} elements already fetched.")
                        continue

                    logger.info(f"Found {len(all_ids)} materials, {len(new_ids)} new to fetch.")

                    # Process in chunks
                    # We need summary fields AND elasticity fields.
                    # The summary endpoint contains elasticity data in the 'elasticity' field or flattened fields?
                    # Based on tests, summary doc has `bulk_modulus` and `shear_modulus` as keys which contain the Voigt/Reuss/VRH values in a dictionary.

                    fields = [
                        "material_id",
                        "formula_pretty",
                        "nsites",
                        "energy_above_hull",
                        "formation_energy_per_atom",
                        "is_stable",
                        "volume",
                        "density",
                        "band_gap",
                        "bulk_modulus",
                        "shear_modulus"
                    ]

                    for i in tqdm(range(0, len(new_ids), CHUNK_SIZE), desc=f"Processing {n}-element materials"):
                        chunk_ids = new_ids[i:i + CHUNK_SIZE]

                        try:
                            # Note: Not all materials have elasticity data computed.
                            # The summary search will return None or empty dict for missing data.
                            chunk_docs = mpr.materials.summary.search(
                                material_ids=chunk_ids,
                                fields=fields
                            )

                            data = []
                            for doc in chunk_docs:
                                # Extract elasticity - robust extraction
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
                                        # If it's a single value, assume it's VRH or similar average
                                        k_vrh = doc.bulk_modulus

                                if doc.shear_modulus is not None:
                                    if isinstance(doc.shear_modulus, dict):
                                        g_voigt = doc.shear_modulus.get('voigt')
                                        g_reuss = doc.shear_modulus.get('reuss')
                                        g_vrh = doc.shear_modulus.get('vrh')
                                    elif isinstance(doc.shear_modulus, (int, float)):
                                        g_vrh = doc.shear_modulus

                                entry = {
                                    "Material ID": str(doc.material_id),
                                    "Formula": doc.formula_pretty,
                                    "Sites": doc.nsites,
                                    "Energy above Hull": doc.energy_above_hull,
                                    "Formation Energy": doc.formation_energy_per_atom,
                                    "Predicted Stable": doc.is_stable,
                                    "Volume": doc.volume,
                                    "Density": doc.density,
                                    "Band Gap": doc.band_gap,
                                    "Bulk Modulus Voigt": k_voigt,
                                    "Bulk Modulus Reuss": k_reuss,
                                    "Bulk Modulus VRH": k_vrh,
                                    "Shear Modulus Voigt": g_voigt,
                                    "Shear Modulus Reuss": g_reuss,
                                    "Shear Modulus VRH": g_vrh
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

            # Finalize: Create the requested output file without Material ID
            finalize_output()

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)

def finalize_output():
    """Reads the working file and saves the final output without Material ID."""
    logger.info(f"Creating final output file {FINAL_OUTPUT_FILE}...")
    try:
        if os.path.exists(WORKING_FILE):
             # Read iterator to handle large files if necessary, but here we just read all
            df = pd.read_csv(WORKING_FILE)

            # Columns requested
            columns = [
                "Formula", "Sites", "Energy above Hull", "Formation Energy",
                "Predicted Stable", "Volume", "Density", "Band Gap",
                "Bulk Modulus Voigt", "Bulk Modulus Reuss", "Bulk Modulus VRH",
                "Shear Modulus Voigt", "Shear Modulus Reuss", "Shear Modulus VRH"
            ]

            # Filter columns
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
