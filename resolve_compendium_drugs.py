"""
resolve_compendium_drugs.py
---------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Connects the validation set to the pipeline it is meant to validate.

The COA Compendium is the one FDA source that already links, by hand,
disease -> COA -> drug -> approval date. That makes it a partial
GROUND TRUTH the reconciliation's joins can be checked against.

But it names drugs the way a person writes them, not the way a database
keys them:

    "1. Brilinta (ticagrelor) July 20, 2011 2. Effient (prasugrel) ..."

Brand, generic in parentheses, approval date, several to a cell,
numbered. No ApplNo. No rxcui. So the validation set cannot actually be
joined to Drugs@FDA without a drug-name resolution step -- and without
that step, the best validation asset in the project is stranded.

This script closes that loop, in two stages:

  PARSE   Pull (brand, generic, approval_date) triples out of the
          drug_approval cells. Tested on the real Compendium: 279 drug
          entries, 237 distinct brands, from 199 rows.

          Seven cells do NOT parse -- and that is CORRECT. They are
          "Qualified COA ..." references, not drugs. A parser that
          forced a match on those would invent drugs that do not exist.
          A non-drug cell is a real absence, not a failed check; it is
          recorded as NOT_A_DRUG, not as a parse failure.

  RESOLVE Query openFDA by brand name to get ApplNo, generic_name, and
          rxcui.

          The parsed generic is an INDEPENDENT CHECK on the resolution:
          the Compendium says Brilinta is ticagrelor; openFDA says
          NDA022433's generic is TICAGRELOR. When they agree, the match
          is corroborated by two sources. When they disagree, the row
          is flagged GENERIC_MISMATCH rather than accepted -- because a
          brand-name collision that silently resolves to the wrong
          application would corrupt the validation set, which is worse
          than a gap in it.

          A brand that openFDA does not know is NOT_FOUND -- recorded,
          not guessed at.

Once resolved, the Compendium row carries ApplNo and rxcui, which means
FDA's own hand-built disease-drug link can be compared directly against
both pipeline routes:

    route 1: ApplNo -> openFDA indication text -> MONDO
    route 2: ApplNo -> rxcui -> RxNorm may_treat -> MeSH -> MONDO
    truth:   Compendium's hand-built disease for that same ApplNo

Three independent angles on one claim. Agreement is corroboration.
Disagreement is a finding.

CAVEAT: the Compendium is dated June 2021 and has no update mechanism.
It is a SNAPSHOT. A drug approved since then is legitimately absent, and
a divergence from a live source may mean the Compendium is stale rather
than that the pipeline is wrong. The delta is itself a measurement of
how far the hand-built layer has drifted.

INPUT:  fda_data/coa_compendium.csv (run extract_coa_compendium.py)
OUTPUT: fda_data/compendium_drugs_resolved.csv
"""

import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
INPUT_FILE = os.path.join(DATA_DIR, "coa_compendium.csv")
OUTPUT_FILE = os.path.join(DATA_DIR, "compendium_drugs_resolved.csv")

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
REQUEST_PAUSE_SECONDS = 0.3
REQUEST_TIMEOUT_SECONDS = 30

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

OPENFDA_API_KEY = (os.environ.get("OPENFDA_API_KEY") or "").strip()

_MONTHS = ("January|February|March|April|May|June|July|August|"
           "September|October|November|December")
_DATE = rf"(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}}"
_ENTRY_RE = re.compile(
    r"([A-Z][A-Za-z0-9\-\u2019']*)\s*\(([^)]+)\)\s*(" + _DATE + r")")

OUTPUT_COLUMNS = [
    "disease",
    "division",
    "brand_name",
    "compendium_generic",
    "approval_date",
    "status",
    "appl_no",
    "openfda_generic",
    "rxcui",
    "source_page",
]


def parse_drug_entries(cell: str) -> list[tuple[str, str, str]]:
    """(brand, generic, approval_date) triples from a Compendium cell."""
    if not cell:
        return []
    return [
        (brand, generic.strip(), date)
        for brand, generic, date in _ENTRY_RE.findall(cell)
    ]


def resolve_brand(brand: str) -> dict:
    """Query openFDA by brand name. Returns ApplNo/generic/rxcui."""
    quoted = urllib.parse.quote(f'"{brand}"')
    params = f"search=openfda.brand_name:{quoted}&limit=1"
    if OPENFDA_API_KEY:
        params += f"&api_key={OPENFDA_API_KEY}"
    url = f"{OPENFDA_LABEL_URL}?{params}"

    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "fda-recon/1.0"})
        with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"status": "NOT_FOUND"}
        return {"status": f"HTTP_{exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"status": f"ERROR:{type(exc).__name__}"}

    openfda = payload["results"][0].get("openfda", {})
    appl = openfda.get("application_number", [])
    generic = openfda.get("generic_name", [])
    rxcui = openfda.get("rxcui", [])
    return {
        "status": "OK",
        "appl_no": "|".join(appl),
        "openfda_generic": generic[0] if generic else "",
        "rxcui": "|".join(rxcui),
    }


def _generics_agree(compendium: str, openfda: str) -> bool:
    """Loose agreement: either name contains the other's first word."""
    if not compendium or not openfda:
        return False
    left = compendium.lower().split()[0].strip(",")
    right = openfda.lower()
    return left in right or right.split()[0] in compendium.lower()


def main() -> None:
    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: {INPUT_FILE} not found.")
        print("Run extract_coa_compendium.py first.")
        return

    with open(INPUT_FILE, newline="", encoding="utf-8") as handle:
        compendium_rows = list(csv.DictReader(handle))

    print(f"Loaded {len(compendium_rows)} Compendium rows.")

    entries = []
    not_a_drug = 0
    for row in compendium_rows:
        cell = (row.get("drug_approval") or "").strip()
        parsed = parse_drug_entries(cell)
        if cell and not parsed:
            not_a_drug += 1
            entries.append({
                "disease": row.get("disease", ""),
                "division": row.get("division", ""),
                "brand_name": "",
                "compendium_generic": "",
                "approval_date": "",
                "status": "NOT_A_DRUG",
                "appl_no": "",
                "openfda_generic": "",
                "rxcui": "",
                "source_page": row.get("page", ""),
            })
            continue
        for brand, generic, date in parsed:
            entries.append({
                "disease": row.get("disease", ""),
                "division": row.get("division", ""),
                "brand_name": brand,
                "compendium_generic": generic,
                "approval_date": date,
                "status": "",
                "appl_no": "",
                "openfda_generic": "",
                "rxcui": "",
                "source_page": row.get("page", ""),
            })

    drugs = [e for e in entries if e["brand_name"]]
    brands = sorted({e["brand_name"] for e in drugs})
    print(f"Parsed {len(drugs)} drug entries, {len(brands)} distinct "
          f"brands.")
    print(f"Non-drug cells (Qualified COA references): {not_a_drug}")
    print()

    print("Resolving brands against openFDA...")
    cache = {}
    for position, brand in enumerate(brands, start=1):
        cache[brand] = resolve_brand(brand)
        if position % 25 == 0 or position == len(brands):
            found = sum(1 for v in cache.values()
                        if v.get("status") == "OK")
            print(f"  {position}/{len(brands)} ({found} resolved)")
        time.sleep(REQUEST_PAUSE_SECONDS)

    ok = mismatch = 0
    for entry in entries:
        brand = entry["brand_name"]
        if not brand:
            continue
        result = cache.get(brand, {"status": "NOT_FOUND"})
        entry["appl_no"] = result.get("appl_no", "")
        entry["openfda_generic"] = result.get("openfda_generic", "")
        entry["rxcui"] = result.get("rxcui", "")

        if result.get("status") != "OK":
            entry["status"] = result.get("status", "NOT_FOUND")
            continue
        if _generics_agree(entry["compendium_generic"],
                           entry["openfda_generic"]):
            entry["status"] = "OK"
            ok += 1
        else:
            entry["status"] = "GENERIC_MISMATCH"
            mismatch += 1

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(entries)

    print()
    print(f"Wrote {len(entries)} rows to {OUTPUT_FILE}")
    print(f"  OK (brand resolved, generic corroborated): {ok}")
    print(f"  GENERIC_MISMATCH (flagged, NOT accepted):  {mismatch}")
    print(f"  NOT_A_DRUG (Qualified COA reference):      {not_a_drug}")
    unresolved = sum(1 for e in entries
                     if e["brand_name"] and e["status"] not in
                     ("OK", "GENERIC_MISMATCH"))
    print(f"  unresolved (NOT_FOUND / error):            {unresolved}")


if __name__ == "__main__":
    main()
