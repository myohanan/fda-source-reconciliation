"""
test_axes_definitions.py
------------------------
Do NCIt's instrument definitions follow a TEMPLATE, or did we get lucky?

The ADSD's NCI definition reads:

    "A SIX-ITEM SELF-ADMINISTERED questionnaire, developed by Gater et
     al. in 2016, that utilizes a TEN-POINT RATING SCALE to assess a
     patient's experience with core asthma symptoms during the
     PRECEDING DAY."

Six axes in one sentence: STRUCTURE, REPORTER, SCALE, RECALL, CONCEPT,
DEVELOPER.

That is either a TEMPLATE followed across the terminology, or one
well-curated concept. The difference is the entire claim, and it is
answerable by counting. One example proves nothing.
"""
import csv
import json
import re
import time
import urllib.request

EVS = "https://api-evsrest.nci.nih.gov/api/v1"
H = {"User-Agent": "fda-recon/1.0", "Accept": "application/json"}
INPUT = "fda_data/cdisc_instruments.csv"
OUTPUT = "fda_data/cdisc_definitions.csv"

# Each axis, as it would appear in a definition sentence.
AXIS_PATTERNS = {
    "STRUCTURE": re.compile(
        r"\b(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty)[- ]item\b", re.I),
    "REPORTER": re.compile(
        r"\b(self[- ]administered|self[- ]report|patient[- ]reported|"
        r"clinician[- ]reported|observer[- ]reported|interviewer[- ]"
        r"administered|proxy[- ]administered|performance)\b", re.I),
    "SCALE": re.compile(
        r"\b(\d{1,2}[- ]point|likert|visual analog|analogue|"
        r"\d\s*(?:to|-)\s*\d\s*(?:rating|scale|point))\b", re.I),
    "RECALL": re.compile(
        r"\b(preceding day|past \d+ (?:hours|days|weeks)|last \d+ "
        r"(?:hours|days|weeks)|past week|past month|previous \d+ "
        r"(?:hours|days|weeks)|daily|weekly|24[- ]hour|7[- ]day)\b",
        re.I),
    "DEVELOPER": re.compile(
        r"\b(developed by|adapted from|created by)\b", re.I),
}


def definition(code: str) -> str:
    """The NCI definition of a concept, or empty."""
    url = f"{EVS}/concept/ncit/{code}?include=definitions"
    try:
        d = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers=H), timeout=40))
    except Exception:
        return ""
    for entry in d.get("definitions", []):
        if entry.get("source") == "NCI":
            return entry.get("definition", "")
    defs = d.get("definitions", [])
    return defs[0].get("definition", "") if defs else ""


rows = list(csv.DictReader(open(INPUT, newline="", encoding="utf-8")))
print(f"instruments: {len(rows)}")
print()

out = []
found = {axis: 0 for axis in AXIS_PATTERNS}
no_definition = 0

for i, r in enumerate(rows, 1):
    # the codelist code -> the INSTRUMENT concept is a sibling; use the
    # instrument name to find it is unreliable, so read the codelist's
    # own definition, which NCI also writes.
    text = definition(r["code"])
    if not text:
        no_definition += 1

    hits = {}
    for axis, rx in AXIS_PATTERNS.items():
        m = rx.search(text)
        if m:
            found[axis] += 1
            hits[axis] = m.group(0)

    out.append({
        "code": r["code"],
        "instrument": r["instrument"],
        "item_count_declared": r["item_count"],
        "definition": text[:300],
        "axes_found": "|".join(sorted(hits)),
        "n_axes": len(hits),
        **{f"axis_{a.lower()}": hits.get(a, "") for a in AXIS_PATTERNS},
    })

    if i % 25 == 0 or i == len(rows):
        print(f"  {i}/{len(rows)}")
    time.sleep(0.12)

cols = (["code", "instrument", "item_count_declared", "n_axes",
         "axes_found"]
        + [f"axis_{a.lower()}" for a in AXIS_PATTERNS]
        + ["definition"])
with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(out)

print()
print("=" * 68)
print("DOES THE TEMPLATE HOLD?")
print("=" * 68)
n = len(rows)
print(f"  instruments with NO definition at all : {no_definition}/{n}")
print()
for axis in AXIS_PATTERNS:
    c = found[axis]
    pct = 100 * c // n if n else 0
    bar = "#" * (pct // 2)
    print(f"  {axis:<10} {c:>3}/{n}  ({pct:>3}%)  {bar}")

print()
print("  axes per instrument:")
dist = {}
for r in out:
    dist[r["n_axes"]] = dist.get(r["n_axes"], 0) + 1
for k in sorted(dist):
    print(f"    {k} axes  {dist[k]:>3}  {'#' * min(dist[k], 50)}")

print()
print("=== instruments where ALL FIVE axes are stated ===")
for r in [x for x in out if x["n_axes"] == 5][:8]:
    print(f"  {r['instrument'][:44]}")
    print(f"      {r['definition'][:110]}")

print()
print(f"Wrote {OUTPUT}")
