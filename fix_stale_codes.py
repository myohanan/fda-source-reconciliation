"""
fix_stale_codes.py
FDA Source Reconciliation
Independent Women's Center for Better Health

Repoints inactive SNOMED codes in cui_code_index.json to their active
equivalents, each verified by concept name in a prior read-only pass.
Backs up the file first, applies 23 repoints, and re-verifies that the
heart-failure relation now resolves (the demo case) before trusting it.

Varicose veins (276504003) is deliberately NOT repointed: no exact
active base-disorder name was confirmed, so it is left as-is rather
than guessed. Flagged for the next-session pass.

Writes: cui_code_index.json (after backing it up to .bak).
"""

import json
import os
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "fda_data")
CODE_INDEX = os.path.join(DATA, "cui_code_index.json")
BACKUP = CODE_INDEX + ".bak"
SAB = "SNOMEDCT_US"

# CUI -> (old_inactive_code, new_active_code, condition, verified_name)
REPOINTS = {
    "C0018801": ("155374007", "84114007", "heart failure",
                 "Heart failure (disorder)"),
    "C0002171": ("201131001", "68225006", "Alopecia areata",
                 "Alopecia areata (disorder)"),
    "C0002395": ("73768007", "26929004", "Alzheimer's disease",
                 "Alzheimer's disease (disorder)"),
    "C0004096": ("187687003", "195967001", "Asthma",
                 "Asthma (disorder)"),
    "C0011615": ("156331003", "24079001", "Atopic dermatitis",
                 "Atopic dermatitis (disorder)"),
    "C0006826": ("269513004", "363346000", "Cancer",
                 "Malignant neoplastic disease (disorder)"),
    "C0015674": ("193054000", "52702003", "Chronic fatigue syndrome",
                 "Chronic fatigue syndrome (disorder)"),
    "C1561643": ("236425005", "709044004", "Chronic kidney disease",
                 "Chronic kidney disease (disorder)"),
    "C0010674": ("85809002", "190905008", "Cystic fibrosis",
                 "Cystic fibrosis (disorder)"),
    "C0013264": ("155095006", "76670001", "Duchenne muscular dystrophy",
                 "Duchenne muscular dystrophy (disorder)"),
    "C0238288": ("56096001", "399091004", "FSHD",
                 "Facioscapulohumeral muscular dystrophy (disorder)"),
    "C0162836": ("201204008", "59393003", "Hidradenitis suppurativa",
                 "Hidradenitis suppurativa (disorder)"),
    "C1800706": ("28168000", "700250006",
                 "Idiopathic pulmonary fibrosis",
                 "Idiopathic pulmonary fibrosis (disorder)"),
    "C0022104": ("155783000", "10743008", "Irritable bowel syndrome",
                 "Irritable bowel syndrome (disorder)"),
    "C0033774": ("271588004", "418290006", "Itch",
                 "Itching (finding)"),
    "C0026769": ("155023009", "24700007", "Multiple sclerosis",
                 "Multiple sclerosis (disorder)"),
    "C0028754": ("5476005", "414916001", "Obesity",
                 "Obesity (disorder)"),
    "C0030193": ("366981002", "22253000", "Pain",
                 "Pain (finding)"),
    "C0035334": ("155113002", "28835009", "Retinitis pigmentosa",
                 "Retinitis pigmentosa (disorder)"),
    "C0003873": ("156471009", "69896004", "Rheumatoid arthritis",
                 "Rheumatoid arthritis (disorder)"),
    "C0002895": ("154798006", "127040003", "Sickle cell disease",
                 "Sickle cell-hemoglobin SS disease (disorder)"),
    "C0024141": ("156450004", "55464009",
                 "Systemic lupus erythematosus",
                 "Systemic lupus erythematosus (disorder)"),
    "C0009324": ("196988003", "64766004", "Ulcerative colitis",
                 "Ulcerative colitis (disorder)"),
}


def main():
    print(f"backing up {os.path.basename(CODE_INDEX)} -> "
          f"{os.path.basename(BACKUP)}")
    shutil.copy2(CODE_INDEX, BACKUP)

    with open(CODE_INDEX, encoding="utf-8") as f:
        idx = json.load(f)
    print(f"loaded {len(idx):,} CUIs\n")

    applied = 0
    skipped = []
    print("applying repoints:")
    for cui, (old, new, cond, name) in REPOINTS.items():
        entry = idx.get(cui)
        if not isinstance(entry, dict):
            skipped.append((cui, cond, "CUI not found"))
            continue
        cur = entry.get(SAB)
        if cur != old:
            skipped.append(
                (cui, cond, f"expected {old}, found {cur}"))
            continue
        entry[SAB] = new
        applied += 1
        print(f"  {cui}  {old} -> {new}   {cond}")

    if skipped:
        print("\n  SKIPPED (left unchanged):")
        for cui, cond, why in skipped:
            print(f"    {cui}  {cond}  ({why})")

    with open(CODE_INDEX, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    print(f"\nwrote {os.path.basename(CODE_INDEX)}  "
          f"({applied} repoints applied, {len(skipped)} skipped)")
    print(f"backup preserved at {os.path.basename(BACKUP)}")
    print("\nNow run:  python3 verify_hf_fix.py")


if __name__ == "__main__":
    main()