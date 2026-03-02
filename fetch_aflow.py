import urllib.request
import json
import pandas as pd
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def fetch_aflow_data():
    """
    Fetches data from AFLOW aflux API based on specific properties and stores it in an Excel file.
    """
    url = "https://aflowlib.org/API/aflux/?Egap(*),Egap_type(*),ael_bulk_modulus_vrh(*),ael_shear_modulus_vrh(*),ael_youngs_modulus_vrh(*),ael_elastic_anisotropy(*),ael_poisson_ratio(*),ael_pughs_modulus_ratio(*),agl_debye(*),agl_gruneisen(*),agl_thermal_conductivity_300K(*),agl_heat_capacity_Cp_300K(*),agl_thermal_expansion_300K(*),agl_acoustic_debye(*),agl_vibrational_entropy_300K_atom(*),agl_vibrational_free_energy_300K_atom(*),enthalpy_formation_atom(*),density(*),paging(0)"
    output_file = "aflow_data.xlsx"

    logger.info(f"Fetching data from: {url}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())

            # The AFLOW API with paging(0) typically returns a dictionary where keys are "X of Y"
            if isinstance(data, dict):
                records = list(data.values())
            elif isinstance(data, list):
                records = data
            else:
                logger.error(f"Unexpected data format received: {type(data)}")
                return

            logger.info(f"Received {len(records)} records from AFLOW.")

            df = pd.DataFrame(records)
            df.to_excel(output_file, index=False)
            logger.info(f"Data successfully saved to {output_file}")

    except Exception as e:
        logger.error(f"An error occurred while fetching or saving data: {e}", exc_info=True)

if __name__ == "__main__":
    fetch_aflow_data()
