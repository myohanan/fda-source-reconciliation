"""
build_code_index.py
-------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Builds the local CUI -> {source: code} index from the UMLS
Metathesaurus release (MRCONSO.RRF), so hierarchy_matcher.code_in can
find a concept's code in each source WITHOUT a live UMLS API call.

WHY THIS EXISTS

code_in currently calls the UMLS API once per (CUI, source) pair to
find a concept's code in a given vocabulary. relate() calls code_in for
every source, for both concepts; the neighbor search calls relate()
against every catalog condition. That is hundreds of live calls for one
no-COA query -- the ~110s hang. The codes do not change between runs
and UMLS already ships them in the release on disk. Read them once.

This does NOT change what code_in returns -- the same source code for
the same CUI -- it removes the network round trip. Same pattern as the
CUI<->SNOMED index and every other local index in this project: parse
the release, write a compact index, keep only what a lookup needs. The
2.3 GB MRCONSO.RRF is STREAMED, never loaded whole.

WHAT IS KEPT

English (LAT == "ENG") rows whose SAB is one of the five UMLS sources
hierarchy_matcher asks: SNOMEDCT_US, MSH, NCI, ICD10CM, MDR. (MONDO is
not a UMLS SAB; it is served from its own local index, separately.)
A concept can carry several codes in one source; the FIRST seen is
kept, matching code_in's own "first atom wins" behaviour.

Output: fda_data/cui_code_index.json
    { "C0018802": {"SNOMEDCT_US": "42343007", "MSH": "D006333", ...} }

MRCONSO.RRF columns (pipe-delimited, no header):
    0 CUI   1 LAT   ...   11 SAB   ...   13 CODE   ...
"""

import json
import os
import sys
import zipfile

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
ZIP_FILE = os.path.join(DATA_DIR, "umls-2026AA-metathesaurus-full.zip")
RRF_PATH = "2026AA/META/MRCONSO.RRF"
INDEX_FILE = os.path.join(DATA_DIR, "cui_code_index.json")

# The five UMLS SABs hierarchy_matcher's SOURCES map asks for.
TARGET_SABS = frozenset({
    "SNOMEDCT_US",
    "MSH",
    "NCI",
    "ICD10CM",
    "MDR",
})
TARGET_LAT = "ENG"

COL_CUI = 0
COL_LAT = 1
COL_SAB = 11
COL_CODE = 13


def build_index(zip_path: str) -> dict:
    """
    Stream MRCONSO.RRF; keep English rows for the five target SABs.
    Build cui -> {sab: code}, first code per (cui, sab) winning to
    match code_in's first-atom-wins behaviour.
    """
    index: dict[str, dict[str, str]] = {}

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(RRF_PATH, "r") as raw:
            for line in raw:
                fields = line.decode("utf-8").split("|")
                if len(fields) <= COL_CODE:
                    continue
                if fields[COL_LAT] != TARGET_LAT:
                    continue
                sab = fields[COL_SAB]
                if sab not in TARGET_SABS:
                    continue
                cui = fields[COL_CUI]
                code = fields[COL_CODE]
                if not cui or not code:
                    continue
                bucket = index.setdefault(cui, {})
                bucket.setdefault(sab, code)

    return index


def main() -> None:
    if not os.path.exists(ZIP_FILE):
        print(f"ERROR: {ZIP_FILE} not found.")
        print("Run download_umls.py first.")
        sys.exit(1)

    print(f"Streaming {RRF_PATH} (2.3 GB; be patient)...")
    index = build_index(ZIP_FILE)

    with open(INDEX_FILE, "w", encoding="utf-8") as handle:
        json.dump(index, handle)

    print()
    print(f"Wrote {INDEX_FILE}")
    print(f"  CUIs indexed: {len(index):,}")
    per_sab: dict[str, int] = {}
    for codes in index.values():
        for sab in codes:
            per_sab[sab] = per_sab.get(sab, 0) + 1
    for sab in sorted(per_sab):
        print(f"    {sab}: {per_sab[sab]:,} concepts")


if __name__ == "__main__":
    main()
