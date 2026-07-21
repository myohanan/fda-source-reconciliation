"""
fix_congestive.py
FDA Source Reconciliation
Independent Women's Center for Better Health

Repoints congestive heart failure (C0018802) from its inactive code
195108009 (not in index) to the active 42343007 "Congestive heart
failure (disorder)", confirmed by name and confirmed to share parent
84114007 (Heart failure) with chronic HF -- restoring the SIBLING
relation the demo relies on for "congestive heart failure" and "CHF".

The relation cache is already empty (cleared earlier) and rebuilds on
next run, so no cache clear is needed. Backs up cui_code_index.json.
"""

import json
import os
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "fda_data")
CODE_INDEX = os.path.join(DATA, "cui_code_index.json")
BACKUP = CODE_INDEX + ".bak2"

CUI = "C0018802"
OLD = "195108009"
NEW = "42343007"


def main():
    shutil.copy2(CODE_INDEX, BACKUP)
    print(f"backed up -> {os.path.basename(BACKUP)}")

    with open(CODE_INDEX, encoding="utf-8") as f:
        idx = json.load(f)

    entry = idx.get(CUI)
    if not isinstance(entry, dict):
        print(f"  {CUI} not found; nothing changed")
        return
    cur = entry.get("SNOMEDCT_US")
    if cur != OLD:
        print(f"  expected {OLD}, found {cur}; leaving unchanged")
        return
    entry["SNOMEDCT_US"] = NEW
    with open(CODE_INDEX, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    print(f"  {CUI}  {OLD} -> {NEW}  congestive heart failure")
    print("done. run: python3 verify_hf_family_final.py")


if __name__ == "__main__":
    main()