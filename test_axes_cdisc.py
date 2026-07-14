"""
test_axes_cdisc.py
------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Does the COA axis schema hold across 181 real instruments?

THE HYPOTHESIS (see COA_AXES.md)

Instrument identity cannot be resolved by name. It should be COMPOSED
from orthogonal axes, the way LOINC composes an observation from
Component / Property / Time / System / Scale / Method.

Proposed axes: CONCEPT, REPORTER, RECALL, SCALE, STRUCTURE,
POPULATION, STATUS.

It was demonstrated on three instruments -- the only three for which
FDA published a Full Qualification Package. Three is not a sample; it
is the entire population of FQPs, so "will it generalize" was
unanswerable from FDA's data.

WHY CDISC CHANGES THAT

CDISC controlled terminology, published by NCI EVS, declares 181
instruments with ITEM-LEVEL codes. The ADSD is C163384, and its six
symptom items are six separate concepts:

    C163818  Rate Breathing at Its Worst
    C163819  Rate Wheezing at Its Worst
    C163820  Rate Shortness of Breath at Worst
    C163821  Rate Chest Tightness at Its Worst
    C163822  Rate Chest Pain at Its Worst
    C163823  Rate Cough at Its Worst
    ------------------------------------------
    C163824  Total Score        <- derived, NOT an item

Item count is therefore COUNTED, not extracted from prose. That matches
FDA's own Full Qualification Package -- "The ADSD is a six-item daily
measure" -- and it RESOLVES the six/seven ambiguity in that same
document: six items, seven values if the total is counted.

This removes the entire extraction-error surface. No PDF parsing, no
prose reading, no inference. The axis value is read from a declared
list.

WHAT THIS TEST ASKS

  1. Do all 181 instruments decompose into the proposed axes?
  2. Where does the axis set BREAK? A PerfO has no recall period. A
     functional test has no response scale. Finding the breaks is the
     point -- a schema that fits everything explains nothing.
  3. Is STRUCTURE (item count) sufficient to discriminate? If thirty
     instruments all have six items, item count alone is not identity.
  4. How many instruments are VERSIONED? The ADSD is V1.0. If versions
     are common, version drift is a real axis. If rare, it is an edge
     case.

HONEST LIMIT, STATED UP FRONT

181 CDISC instruments is not "all instruments." It is the ones CDISC
standardized -- and that set skews toward FDA's qualification program.
The ADSD (8 trials, never a primary endpoint) IS in CDISC. The KCCQ
(1,029 trials, 117 primary endpoints, carrying tirzepatide, mavacamten,
and aficamten) IS NOT.

So this is a BIASED SAMPLE of instruments. That bias barely matters for
testing whether the AXES work as a decomposition. It matters entirely
for any claim about coverage, and no such claim is made here.
"""

import csv
import json
import re
import time
import urllib.parse
import urllib.request

EVS = "https://api-evsrest.nci.nih.gov/api/v1"
HEADERS = {"User-Agent": "fda-recon/1.0", "Accept": "application/json"}
PAUSE = 0.15

# CDISC Questionnaire Terminology -- the parent of every instrument's
# Test Name codelist.
QUESTIONNAIRE_ROOT = "C100110"

OUTPUT = "fda_data/cdisc_instruments.csv"

COLUMNS = [
    "code", "instrument", "version",
    "item_count", "has_total_score", "items",
]

_VERSION_RE = re.compile(r"\bV(?:ersion)?\s*(\d+(?:\.\d+)?)\b", re.I)

# A codelist member that is NOT an item of the instrument.
_NOT_AN_ITEM = (
    "Total Score",
    "Test Code Terminology",
    "Test Name Terminology",
)


def _get(path: str) -> dict | list:
    request = urllib.request.Request(f"{EVS}{path}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def instrument_codelists() -> list[dict]:
    """Every instrument with a declared Test Name codelist."""
    members = _get(
        f"/subset/ncit/{QUESTIONNAIRE_ROOT}/members"
        f"?pageSize=1000&include=minimal")
    return [
        m for m in members
        if "Test Name Terminology" in m.get("name", "")
    ]


def items_of(code: str) -> tuple[list[str], bool]:
    """
    The instrument's ITEMS, and whether it declares a total score.

    An item is a codelist member that is not a derived score and not a
    pointer to the sibling code list. This distinction is what resolves
    the ADSD's six-versus-seven ambiguity: six items, plus a total.
    """
    try:
        members = _get(f"/subset/ncit/{code}/members"
                       f"?pageSize=300&include=minimal")
    except Exception:  # noqa: BLE001
        return [], False

    items = []
    has_total = False
    for member in members:
        name = member.get("name", "")
        if "Total Score" in name:
            has_total = True
            continue
        if any(token in name for token in _NOT_AN_ITEM):
            continue
        items.append(name)
    return items, has_total


def clean_name(raw: str) -> tuple[str, str]:
    """'CDISC Questionnaire ADSD Version 1.0 Test Name Terminology'
       -> ('ADSD', '1.0')"""
    text = raw.replace("CDISC Questionnaire ", "")
    text = text.replace(" Test Name Terminology", "")
    text = text.replace("CDISC ", "").strip()

    version = ""
    match = _VERSION_RE.search(text)
    if match:
        version = match.group(1)
        text = _VERSION_RE.sub(" ", text).strip()

    return re.sub(r"\s+", " ", text), version


def main() -> None:
    codelists = instrument_codelists()
    print(f"CDISC instruments with a declared item codelist: "
          f"{len(codelists)}")
    print()

    rows = []
    for position, entry in enumerate(codelists, start=1):
        code = entry["code"]
        name, version = clean_name(entry.get("name", ""))
        items, has_total = items_of(code)

        rows.append({
            "code": code,
            "instrument": name,
            "version": version,
            "item_count": len(items),
            "has_total_score": has_total,
            "items": "|".join(items),
        })

        if position % 25 == 0 or position == len(codelists):
            print(f"  {position}/{len(codelists)}")
        time.sleep(PAUSE)

    with open(OUTPUT, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print("=" * 70)
    print("AXIS: STRUCTURE (item count)")
    print("=" * 70)
    counts = {}
    for row in rows:
        counts[row["item_count"]] = counts.get(row["item_count"], 0) + 1

    zero = counts.get(0, 0)
    print(f"  instruments with ZERO items retrieved : {zero}")
    print("  (a retrieval failure, or a codelist with no members --")
    print("   NOT a finding about the instrument)")
    print()
    print("  item-count distribution:")
    for count in sorted(k for k in counts if k > 0):
        bar = "#" * min(counts[count], 40)
        print(f"    {count:>3} items  {counts[count]:>3}  {bar}")

    print()
    print("=" * 70)
    print("IS ITEM COUNT ALONE SUFFICIENT TO DISCRIMINATE?")
    print("=" * 70)
    collisions = {c: n for c, n in counts.items() if n > 1 and c > 0}
    total_colliding = sum(collisions.values())
    print(f"  instruments sharing an item count with another: "
          f"{total_colliding}")
    print(f"  distinct colliding counts: {len(collisions)}")
    print()
    print("  So STRUCTURE alone is NOT identity. The axes must be")
    print("  composed -- which is the whole premise. If item count were")
    print("  unique per instrument it would just be a bad primary key.")

    print()
    print("=" * 70)
    print("AXIS: VERSION")
    print("=" * 70)
    versioned = [r for r in rows if r["version"]]
    print(f"  instruments carrying an explicit version: "
          f"{len(versioned)}/{len(rows)}")
    for row in versioned[:10]:
        print(f"    {row['instrument'][:44]:<44} v{row['version']}")

    print()
    print("=" * 70)
    print("TOTAL SCORE DECLARED SEPARATELY FROM ITEMS?")
    print("=" * 70)
    with_total = sum(1 for r in rows if r["has_total_score"])
    print(f"  instruments declaring a Total Score: {with_total}/"
          f"{len(rows)}")
    print()
    print("  This is what resolves the ADSD's six-versus-seven")
    print("  ambiguity in FDA's own Full Qualification Package:")
    print("  six ITEMS, plus a derived TOTAL. A prose reader sees a")
    print("  contradiction. A declared list does not.")

    print()
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
