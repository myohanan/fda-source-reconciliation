import os
import urllib.request
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["UMLS_API_KEY"]

RELEASE_URL = ("https://download.nlm.nih.gov/mlb/utsauth/USExt/"
               "SnomedCT_ManagedServiceUS_PRODUCTION_US1000124_"
               "20260301T120000Z.zip")
DEST = os.path.join("fda_data",
                    "SnomedCT_USEdition_20260301.zip")

url = f"https://uts-ws.nlm.nih.gov/download?url={RELEASE_URL}&apiKey={KEY}"

print("Downloading SNOMED CT US Edition (~1 GB, be patient)...")
urllib.request.urlretrieve(url, DEST)
size = os.path.getsize(DEST)
print(f"Done: {DEST} ({size:,} bytes)")
