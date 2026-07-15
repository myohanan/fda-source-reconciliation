import os
import urllib.request
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["UMLS_API_KEY"]

RELEASE_URL = ("https://download.nlm.nih.gov/umls/kss/2026AA/"
               "umls-2026AA-metathesaurus-full.zip")
DEST = os.path.join("fda_data", "umls-2026AA-metathesaurus-full.zip")

url = f"https://uts-ws.nlm.nih.gov/download?url={RELEASE_URL}&apiKey={KEY}"

print("Downloading UMLS 2026AA Metathesaurus full (~5 GB, slow)...")
print("This is large. Let it run.")
urllib.request.urlretrieve(url, DEST)
size = os.path.getsize(DEST)
print(f"Done: {DEST} ({size:,} bytes)")
