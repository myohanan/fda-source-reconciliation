"""
Has any qualified COA ever been used to approve a drug?

The COA Compendium is FDA's own hand-built table linking a disease, an
endpoint, and the DRUG APPROVED USING IT. So it is the only source that
can answer the question a sponsor most wants answered:

    Is this instrument a proven path to approval, or has it never been
    used for one?

This is a PROBE, not a tool. It measures before anything is built.
"""
import csv
import re

QUALIFIED = "fda_data/qualified_coas.csv"
SUBMISSIONS = "fda_data/coa_submissions.csv"
COMPENDIUM = "fda_data/coa_compendium.csv"


def norm(s):
    s = re.sub(r"\s*\([^)]*\)", " ", s or "")
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def instrument_name(raw):
    """'DDT COA #000084: Kansas City Cardiomyopathy Questionnaire (KCCQ)'
       -> 'Kansas City Cardiomyopathy Questionnaire'"""
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    return norm(raw)


qualified, submitted = [], []
for path, bucket in ((QUALIFIED, qualified), (SUBMISSIONS, submitted)):
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            name = r.get("DDT COA Number and Instrument Name", "")
            if name:
                bucket.append({
                    "raw": name,
                    "instrument": instrument_name(name),
                    "condition": r.get("Disease/Condition", ""),
                })

comp = list(csv.DictReader(open(COMPENDIUM, newline="",
                                encoding="utf-8")))

print(f"qualified COAs   : {len(qualified)}")
print(f"submitted COAs   : {len(submitted)}")
print(f"compendium rows  : {len(comp)}")
print()


def find_in_compendium(coa):
    """Does the Compendium name this instrument, and with what drug?"""
    hits = []
    words = [w for w in coa["instrument"].split() if len(w) > 4]
    if not words:
        return hits
    for row in comp:
        blob = norm(row["coa_tool_type"] + " " + row["concept"])
        # require MOST of the instrument's distinctive words present
        present = sum(1 for w in words if w in blob)
        if present >= max(2, len(words) - 1):
            hits.append({
                "disease": row["disease"],
                "tool": row["coa_tool_type"],
                "drug": row["drug_approval"],
            })
    return hits


print("=" * 70)
print("THE 7 QUALIFIED COAs -- has any drug been approved using one?")
print("=" * 70)
used, unused = 0, 0
for coa in qualified:
    hits = find_in_compendium(coa)
    print()
    print(f"  {coa['raw'][:66]}")
    print(f"      condition: {coa['condition'][:50]}")
    if hits:
        used += 1
        for h in hits[:3]:
            print(f"      IN COMPENDIUM: {h['disease'][:34]}")
            print(f"          drug: {h['drug'][:60]}")
    else:
        unused += 1
        print("      NOT FOUND in the Compendium.")
        print("      No drug approval on record used this instrument.")

print()
print("=" * 70)
print(f"  qualified COAs appearing in the Compendium : {used}/7")
print(f"  qualified COAs with NO approval on record  : {unused}/7")
print("=" * 70)
