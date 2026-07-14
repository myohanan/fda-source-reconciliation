"""
What has FDA approved since its own endpoint record stopped?

The COA Compendium -- FDA's ONLY source linking a disease to an endpoint
to the DRUG APPROVED USING IT -- was published June 2021 and has never
been reissued. It is a snapshot of 199 rows.

FDA has qualified seven COAs in the program's history. This probe asks
what the frozen Compendium cannot: since it stopped, how many drugs has
FDA ORIGINALLY APPROVED for those same seven conditions?

WHAT THIS DOES NOT CLAIM

It does NOT claim those approvals failed to use the qualified COA. That
link does not exist in ANY FDA source. THAT IS THE POINT.

FDA qualified seven instruments. The only record that ever tracked
endpoint-to-approval links is a PDF that stopped in 2021. So there is no
way, from any FDA source, to answer: "has the KCCQ ever supported an
approval?"

This is not a scandal. It is an ARCHITECTURAL gap. The qualification
program produces instruments. The approval system produces drugs.
Nothing connects them -- so FDA cannot measure whether its own program
works.

METHOD
  original approvals only  (SubmissionType=ORIG, SubmissionStatus=AP)
  approved on or after     June 2021
  indication matched via   term_match_util (whole-word guard on short
                           terms), against openFDA indication prose --
                           free text with no code, which is exactly the
                           case that utility exists for
"""
import csv
from collections import defaultdict

import term_match_util as tm

INDICATIONS = "fda_data/openfda_indications.csv"
SUBMISSIONS = "fda_data/drugsatfda/Submissions.txt"
QUALIFIED = "fda_data/qualified_coas.csv"

COMPENDIUM_FROZEN = "2021-06-01"

CONDITION_TERMS = {
    "Chronic Heart Failure (CHF)": ["heart failure"],
    "Major Depressive Disorder (MDD)": ["major depressive disorder"],
    "Irritable Bowel Syndrome (IBS)": ["irritable bowel syndrome"],
    "Asthma": ["asthma"],
    "Chronic Obstructive Pulmonary Disease (COPD)":
        ["chronic obstructive pulmonary disease"],
    "Acute Bacterial Exacerbation of Chronic Bronchitis in patients "
    "with Chronic Obstructive Pulmonary Disease (ABECB-COPD)":
        ["chronic bronchitis"],
    "Non-Small Cell Lung Cancer (NSCLC)":
        ["non-small cell lung cancer", "non small cell lung cancer"],
}

# --- original approval date per ApplNo
approved: dict[str, str] = {}
with open(SUBMISSIONS, newline="", encoding="utf-8",
          errors="ignore") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        if row.get("SubmissionType") != "ORIG":
            continue
        if row.get("SubmissionStatus") != "AP":
            continue
        date = (row.get("SubmissionStatusDate") or "")[:10]
        appl = (row.get("ApplNo") or "").strip()
        if appl and date:
            # keep the earliest ORIG approval
            if appl not in approved or date < approved[appl]:
                approved[appl] = date

print(f"original approvals in Drugs@FDA: {len(approved)}")

rows = list(csv.DictReader(open(INDICATIONS, newline="",
                                encoding="utf-8")))
ok = [r for r in rows if r["status"] == "OK" and r["indication_text"]]
print(f"applications with indication text: {len(ok)}")
print(f"FDA's endpoint record froze: {COMPENDIUM_FROZEN}")
print()

hits = defaultdict(list)
for row in ok:
    appl = row["ApplNo"].strip()
    date = approved.get(appl)
    if not date or date < COMPENDIUM_FROZEN:
        continue
    text = row["indication_text"].lower()
    for condition, terms in CONDITION_TERMS.items():
        for term in terms:
            if tm.term_matches(term, text):
                hits[condition].append({
                    "appl": f'{row["ApplType"]}{appl}',
                    "date": date,
                    "brand": row["brand_name"],
                    "generic": row["generic_name"][:32],
                })
                break

print("=" * 72)
print("ORIGINAL APPROVALS SINCE JUNE 2021")
print("for the seven conditions where FDA has QUALIFIED a COA")
print("=" * 72)

qualified = list(csv.DictReader(open(QUALIFIED, newline="",
                                     encoding="utf-8")))
for coa in qualified:
    condition = coa["Disease/Condition"]
    found = sorted(hits.get(condition, []), key=lambda d: d["date"])
    print()
    print(f'  {coa["DDT COA Number and Instrument Name"][:62]}')
    print(f'      condition: {condition[:56]}')
    print(f'      NEW approvals since the record froze: {len(found)}')
    for d in found:
        print(f'          {d["date"]}  {d["appl"]:<11} '
              f'{d["brand"][:22]:<22} {d["generic"]}')

total = sum(len(v) for v in hits.values())
print()
print("=" * 72)
print(f'  Original approvals since June 2021 for a qualified-COA')
print(f'  condition: {total}')
print()
print("  For NONE of them does any FDA source record which endpoint")
print("  was used. There is no mechanism to know whether a single one")
print("  of the seven qualified COAs has ever supported an approval.")
print("=" * 72)
