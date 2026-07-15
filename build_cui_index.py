"""
build_cui_index.py
------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Builds the local CUI <-> SNOMED bridge from the UMLS Metathesaurus
release (MRCONSO.RRF), so the resolver can map a SNOMED code to a UMLS
concept -- and back -- WITHOUT a live API call.

WHY THIS EXISTS

The neighbor walk resolves every structural neighbor to a CUI so it can
be matched against the catalog. Done live, that is one full network
resolution per neighbor -- dozens per query, ~110 seconds for a no-COA
disease, and slow on the FIRST run of every disease, which no result
cache can fix. UMLS IS the authority for CUI<->code identity, and the
full release carries that mapping on disk. Read it once; never ask the
API for it again.

This is the same pattern as every other index in this project: parse
the raw release, write a compact index, keep nothing in memory that a
lookup does not need. The 2.3 GB MRCONSO.RRF is STREAMED line by line;
it is never loaded whole.

WHAT IS KEPT

Only English (LAT == "ENG") atoms from SNOMEDCT_US. MRCONSO carries
every vocabulary and language; we need one vocabulary, one language.
A concept can have several SNOMED codes (a preferred term plus
synonyms mapped to related codes); ALL are captured, so a neighbor
carrying any of them still resolves.

Output: fda_data/cui_snomed_index.json
    {
      "code_to_cui": { "42343007": "C0018802", ... },
      "cui_to_codes": { "C0018802": ["42343007", "84114007"], ... }
    }

MRCONSO.RRF columns (pipe-delimited, no header):
    0 CUI   1 LAT   ...   11 SAB   ...   13 CODE   14 STR   ...
"""

import json
import os
import sys
import zipfile

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
ZIP_FILE = os.path.join(DATA_DIR, "umls-2026AA-metathesaurus-full.zip")
RRF_PATH = "2026AA/META/MRCONSO.RRF"
INDEX_FILE = os.path.join(DATA_DIR, "cui_snomed_index.json")

TARGET_SAB = "SNOMEDCT_US"
TARGET_LAT = "ENG"

COL_CUI = 0
COL_LAT = 1
COL_SAB = 11
COL_CODE = 13


def build_index(zip_path: str) -> dict:
    """
    Stream MRCONSO.RRF; keep English SNOMEDCT_US atoms only. Build both
    directions: code -> cui (for the neighbor walk) and cui -> codes
    (for the reverse, when a catalog CUI needs its SNOMED codes).
    """
    code_to_cui: dict[str, str] = {}
    cui_to_codes: dict[str, list[str]] = {}

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(RRF_PATH, "r") as raw:
            for line in raw:
                fields = line.decode("utf-8").split("|")
                if len(fields) <= COL_CODE:
                    continue
                if fields[COL_LAT] != TARGET_LAT:
                    continue
                if fields[COL_SAB] != TARGET_SAB:
                    continue
                cui = fields[COL_CUI]
                code = fields[COL_CODE]
                if not cui or not code:
                    continue
                # code -> cui: a SNOMED code belongs to exactly one CUI,
                # so first writer wins and later duplicates agree.
                code_to_cui.setdefault(code, cui)
                bucket = cui_to_codes.setdefault(cui, [])
                if code not in bucket:
                    bucket.append(code)

    return {"code_to_cui": code_to_cui, "cui_to_codes": cui_to_codes}


def main() -> None:
    if not os.path.exists(ZIP_FILE):
        print(f"ERROR: {ZIP_FILE} not found.")
        print("Run download_umls.py first.")
        sys.exit(1)

    print(f"Streaming {RRF_PATH} from {ZIP_FILE} (2.3 GB; be patient)...")
    index = build_index(ZIP_FILE)

    with open(INDEX_FILE, "w", encoding="utf-8") as handle:
        json.dump(index, handle)

    print()
    print(f"Wrote {INDEX_FILE}")
    print(f"  SNOMED codes mapped:  {len(index['code_to_cui']):,}")
    print(f"  CUIs with a SNOMED code: {len(index['cui_to_codes']):,}")
    print(f"Raw release kept at {ZIP_FILE}")


if __name__ == "__main__":
    main()
