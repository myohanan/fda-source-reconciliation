"""
run_coa_usage.py
----------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Has any COA in FDA's catalog ever been used in a trial?

FDA's four sources track QUALIFICATION. Nothing tracks USE. So FDA
cannot see that the KCCQ is a primary endpoint in 117 trials -- carrying
tirzepatide, mavacamten, aficamten -- and it cannot see that its
qualified asthma diary has never been a primary endpoint in any trial.

Both are on the same list. Nothing in any FDA source distinguishes them.

The trial registry knows, because sponsors must declare their endpoints
before the trial runs.

WHAT THIS DOES NOT CLAIM

It reports how many trials REGISTERED an outcome whose text contains the
instrument's name. It does NOT claim those trials used that instrument.
The text search over-returns on purpose -- it is the sensitive screen --
and the verbatim strings are preserved so a human can see the
difference. Searching FDA's "Asthma Daytime Symptom Diary" returns
Regeneron's "Asthma Daily Symptom (ADS) Score," which is a DIFFERENT
instrument.

OUTPUT
  fda_data/coa_usage.csv  one row per COA
"""
import csv
import re
import time

import endpoint_search as es

SUBMISSIONS = "fda_data/coa_submissions.csv"
QUALIFIED = "fda_data/qualified_coas.csv"
OUTPUT = "fda_data/coa_usage.csv"

COLUMNS = [
    "coa_number", "instrument", "condition", "qualified",
    "status", "trials", "as_primary", "as_secondary", "top_sponsors",
]


# Two or more complete "Name (ABBREV)" units in one catalog entry.
# FDA does this when a single COA number covers several instruments.
_MULTI_RE = re.compile(r"([^()]+?)\s*\(([A-Z][A-Za-z0-9\-]*)\)")


def instrument_names(raw: str) -> list[str]:
    """
    The instrument name(s) in a catalog entry.

    ONE CATALOG ENTRY CAN NAME SEVERAL INSTRUMENTS, and searching the
    entry string instead of the instrument names returns nothing --
    because no sponsor writes the entry string.

        catalog:  "Asthma Daytime Symptom Diary (ADSD) and Asthma
                   Nighttime Symptom Diary (ANSD)"
        sponsor:  "Change from baseline in the Asthma Daytime Symptom
                   Diary (ADSD) daily score"        <- Sanofi, NCT06676319

    Searching the catalog string returned 0 trials. Searching the
    COMPONENT returned 8. The registry had the answer the whole time;
    the query was wrong.

    The split is STRUCTURAL, not a guess: a unit is a complete
    "Name (ABBREV)" pair, and an entry only splits when it contains TWO
    OR MORE of them. That distinction matters, and the catalog proves
    it -- of the eight entries containing the word "and", only ONE is
    actually two instruments:

        Asthma Daytime Symptom Diary (ADSD) and Asthma
            Nighttime Symptom Diary (ANSD)        -> TWO units, split
        Hidradenitis Suppurativa Area and Severity Index (HASI)
                                                  -> ONE unit, do not
        Cutaneous Lupus Erythematosus Disease Area and Severity Index
            (CLASI)                               -> ONE unit, do not
        Crohn's Disease Patient-Reported Outcomes Signs and Symptoms
            (CD-PRO/SS)                           -> ONE unit, do not

    A naive split on "and" would have shredded seven instrument names
    to fix one entry. This is the same pattern already used to split
    the CFS/ME/SEID multi-name CONDITION -- one field holding several
    things, which must be searched as several things.
    """
    text = raw.split(":", 1)[1] if ":" in raw else raw
    units = _MULTI_RE.findall(text)

    # TWO PARENTHETICALS DOES NOT MEAN TWO INSTRUMENTS.
    #
    # A first version required only that -- and it produced a phantom
    # instrument called "in Systemic Lupus Erythematosus" with 112
    # trials, because this entry has two "Name (ABBREV)" units:
    #
    #   "Cutaneous Lupus Erythematosus Disease Area and Severity Index
    #    (CLASI) IN Systemic Lupus Erythematosus (SLE)"
    #
    # The second unit is a POPULATION, not an instrument. English
    # grammar carries that distinction and a regex over parentheses
    # does not.
    #
    # The structural test: an instrument name is a NOUN PHRASE. A
    # population qualifier attaches with a PREPOSITION. No instrument
    # name begins with "in", "for", "among", or "with".
    #
    # This is not a semantic judgment -- it is a check on the leading
    # token, and it is the narrowest rule that separates the cases the
    # catalog actually contains:
    #
    #   ADSD (ADSD) and Nighttime Diary (ANSD)  -> both noun phrases
    #                                              -> TWO instruments
    #   CLASI (CLASI) in Systemic Lupus (SLE)   -> second starts "in"
    #                                              -> ONE instrument
    _QUALIFIER_LEAD = ("in ", "for ", "among ", "with ", "and in ")

    candidates = []
    for unit, _abbrev in units:
        cleaned = unit.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered.startswith(_QUALIFIER_LEAD):
            continue          # a population, not an instrument
        candidates.append(re.sub(r"^and\s+", "", cleaned,
                                 flags=re.I).strip())

    if len(candidates) >= 2:
        return candidates

    # one instrument: drop the parenthetical abbreviation
    stripped = re.sub(r"\s*\([^)]*\)", " ", text)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return [stripped] if stripped else []


def coa_number(raw: str) -> str:
    m = re.search(r"(\d{6}|\d{4}-\d+)", raw)
    return m.group(1) if m else ""


coas = []
for path, is_qualified in ((SUBMISSIONS, False), (QUALIFIED, True)):
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            raw = r.get("DDT COA Number and Instrument Name", "")
            for name in instrument_names(raw):
                if len(name) < 6:
                    continue
                coas.append({
                    "coa_number": coa_number(raw),
                    "instrument": name,
                    "condition": r.get("Disease/Condition", ""),
                    "qualified": is_qualified,
                })

print(f"COAs to check: {len(coas)}")
print()

rows = []
for i, coa in enumerate(coas, 1):
    result = es.search(coa["instrument"])
    sponsors = {}
    for t in result["trials"]:
        s = t["sponsor"]
        if s:
            sponsors[s] = sponsors.get(s, 0) + 1
    top = sorted(sponsors.items(), key=lambda kv: -kv[1])[:3]

    # A COA used as a SECONDARY endpoint is being USED. Reporting
    # only the primary count collapses "8 trials, all secondary" into
    # "0 primary" -- which reads identically to "nobody uses this."
    # Those are different facts and the tool already has both.
    as_secondary = sum(
        1 for t in result["trials"]
        if t["matched_secondary"] and not t["matched_primary"])

    rows.append({
        "coa_number": coa["coa_number"],
        "instrument": coa["instrument"],
        "condition": coa["condition"],
        "qualified": coa["qualified"],
        "status": result["status"],
        "trials": result["retrieved"],
        "as_primary": result["as_primary"],
        "as_secondary": as_secondary,
        "top_sponsors": "|".join(f"{s}({n})" for s, n in top),
    })
    mark = " [QUALIFIED]" if coa["qualified"] else ""
    print(f'  {i:>2}/{len(coas)}  {result["retrieved"]:>5} trials  '
          f'{result["as_primary"]:>4} primary  '
          f'{as_secondary:>4} secondary  '
          f'{coa["instrument"][:40]}{mark}')
    time.sleep(0.3)

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(rows)

print()
print("=" * 72)
print("MOST-USED COAs IN FDA'S CATALOG")
print("=" * 72)
for r in sorted(rows, key=lambda r: -r["trials"])[:12]:
    q = " [Q]" if r["qualified"] else "   "
    print(f'  {r["trials"]:>5} trials  {r["as_primary"]:>4} primary  '
          f'{r["as_secondary"]:>4} secondary{q}  '
          f'{r["instrument"][:44]}')

print()
print("=" * 72)
print("NEVER USED -- zero trials register this instrument")
print("=" * 72)
never = [r for r in rows if r["trials"] == 0]
for r in never:
    q = " [QUALIFIED]" if r["qualified"] else ""
    print(f'  {r["instrument"][:56]}{q}')
print()
print(f'  {len(never)} of {len(rows)} COAs appear in NO trial.')
print()
qualified_rows = [r for r in rows if r["qualified"]]
print("THE SEVEN QUALIFIED COAs:")
for r in sorted(qualified_rows, key=lambda r: -r["trials"]):
    print(f'  {r["trials"]:>5} trials  {r["as_primary"]:>4} primary  '
          f'{r["as_secondary"]:>4} secondary  '
          f'{r["instrument"][:44]}')
print()
print(f"Wrote {OUTPUT}")
