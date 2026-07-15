"""
build_hierarchy_index.py
------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Builds a local is-a hierarchy index for the sources that have no local
tree of their own -- ICD10CM, NCI (NCIt), and MDR (MedDRA) -- from the
UMLS release, so hierarchy_matcher._relatives can walk parents and
children WITHOUT a live UMLS API call.

WHY THIS EXISTS

_relatives walks a code's parents/children in one source. SNOMED is
already served from its local is-a index; MeSH has its tree_numbers on
disk. The remaining three -- ICD10CM, NCI, MDR -- had no local tree, so
_relatives called the UMLS API once per (source, code, direction), for
every source, for every catalog condition in the neighbor search. That
is the remaining hang after the code index removed the code lookups.
The trees do not change between runs and the release ships them. Read
them once.

THE JOIN

MRHIER carries the hierarchy in ATOM (AUI) space: each row is an atom,
its source (SAB), and its immediate parent atom (PAUI, column 3).
_relatives works in CODE space. So the tree must be translated AUI ->
code, and MRCONSO carries that map (AUI -> CODE + STR). This builder
streams both files:

  1. MRCONSO: build AUI -> (code, name) for the three target SABs,
     English atoms only.
  2. MRHIER:  for each target-SAB row with a parent, translate both the
     atom's AUI and its PAUI to codes via the map from step 1, and
     record the child_code -> parent_code edge (and its inverse).

SNOMED rows in MRHIER are skipped -- SNOMED is served from its own
index. MeSH is skipped here too; it has its tree_numbers.

Output: fda_data/hierarchy_index.json
    {
      "NCI":     {"parents": {child: [parent,...]},
                  "children": {parent: [child,...]},
                  "names": {code: name}},
      "ICD10CM": {...},
      "MDR":     {...}
    }

Both files are STREAMED; neither (2.3 GB, 7 GB) is loaded whole.
"""

import json
import os
import sys
import zipfile

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
ZIP_FILE = os.path.join(DATA_DIR, "umls-2026AA-metathesaurus-full.zip")
MRCONSO = "2026AA/META/MRCONSO.RRF"
MRHIER = "2026AA/META/MRHIER.RRF"
INDEX_FILE = os.path.join(DATA_DIR, "hierarchy_index.json")

# The sources that need a tree built here. SNOMED (own index) and MeSH
# (tree_numbers) are deliberately excluded.
TARGET_SABS = frozenset({"ICD10CM", "NCI", "MDR"})
TARGET_LAT = "ENG"

# MRCONSO columns
C_CUI, C_LAT, C_AUI, C_SAB, C_CODE, C_STR = 0, 1, 7, 11, 13, 14
# MRHIER columns: CUI|AUI|CTX|PAUI|SAB|RELA|PTR|HCD|CVF
H_AUI, H_PAUI, H_SAB = 1, 3, 4


def _build_aui_map(zf: zipfile.ZipFile) -> dict:
    """AUI -> (code, name) for target-SAB English atoms, from MRCONSO."""
    aui_map: dict[str, tuple[str, str]] = {}
    with zf.open(MRCONSO, "r") as raw:
        for line in raw:
            f = line.decode("utf-8").split("|")
            if len(f) <= C_STR:
                continue
            if f[C_LAT] != TARGET_LAT:
                continue
            if f[C_SAB] not in TARGET_SABS:
                continue
            aui = f[C_AUI]
            code = f[C_CODE]
            if not aui or not code:
                continue
            aui_map.setdefault(aui, (code, f[C_STR]))
    return aui_map


def _build_edges(zf: zipfile.ZipFile, aui_map: dict) -> dict:
    """
    child_code -> parent_code edges per SAB, from MRHIER, translated to
    code space via aui_map. Builds parents, children, and names.
    """
    index: dict[str, dict] = {
        sab: {"parents": {}, "children": {}, "names": {}}
        for sab in TARGET_SABS
    }
    with zf.open(MRHIER, "r") as raw:
        for line in raw:
            f = line.decode("utf-8").split("|")
            if len(f) <= H_SAB:
                continue
            sab = f[H_SAB]
            if sab not in TARGET_SABS:
                continue
            aui = f[H_AUI]
            paui = f[H_PAUI]
            if not aui or not paui:
                continue
            child = aui_map.get(aui)
            parent = aui_map.get(paui)
            if not child or not parent:
                continue
            child_code, child_name = child
            parent_code, parent_name = parent
            if child_code == parent_code:
                continue
            src = index[sab]
            src["names"][child_code] = child_name
            src["names"][parent_code] = parent_name
            p_list = src["parents"].setdefault(child_code, [])
            if parent_code not in p_list:
                p_list.append(parent_code)
            c_list = src["children"].setdefault(parent_code, [])
            if child_code not in c_list:
                c_list.append(child_code)
    return index


def build_index(zip_path: str) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        aui_map = _build_aui_map(zf)
        return _build_edges(zf, aui_map)


def main() -> None:
    if not os.path.exists(ZIP_FILE):
        print(f"ERROR: {ZIP_FILE} not found. Run download_umls.py.")
        sys.exit(1)
    print("Streaming MRCONSO (AUI->code) then MRHIER (tree)...")
    print("Both are large; this takes several minutes.")
    index = build_index(ZIP_FILE)
    with open(INDEX_FILE, "w", encoding="utf-8") as handle:
        json.dump(index, handle)
    print()
    print(f"Wrote {INDEX_FILE}")
    for sab in sorted(index):
        s = index[sab]
        print(f"  {sab}: {len(s['parents']):,} codes with a parent, "
              f"{len(s['children']):,} with children")


if __name__ == "__main__":
    main()
