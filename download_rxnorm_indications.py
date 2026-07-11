"""
download_rxnorm_indications.py
------------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Builds a SECOND, INDEPENDENT route from a drug to its condition.

The openFDA route resolves a drug to a condition by parsing
`indications_and_usage` -- prose. That is the weakest link in the
chain: it is the one step where the pipeline must interpret free text
rather than follow a key.

This script builds a coded alternative. openFDA also returns `rxcui`
for each application. RxNav's RxClass API exposes MED-RT `may_treat`
relationships, which return the drug's indications as MeSH-coded
DISEASE concepts. MONDO carries MeSH cross-references. So the chain
closes with NO prose parsing anywhere in it:

    ApplNo -> rxcui -> may_treat -> MeSH descriptor -> MONDO class

Verified on real records:
    aripiprazole (349490)  -> MeSH D012559  Schizophrenia
    atorvastatin (259255)  -> MeSH D003324  Coronary Artery Disease
                              MeSH D006937  Hypercholesterolemia
    nivolumab+relatlimab   -> MeSH D002289  Carcinoma, Non-Small-Cell
      (2596778)                             Lung

WHY TWO ROUTES, AND WHY THIS IS NOT REDUNDANCY:

The two routes are not a primary and a backup. They are two sources
that carve the drug-to-disease relation from different angles -- one
from the approved label's prose, one from a curated therapeutic
classification. When they AGREE, that is genuine corroboration from
independent evidence. When they DISAGREE, that disagreement is
INFORMATION, not noise: it is a real CONFLICT_DETECTED, and the
resolver should surface it rather than silently prefer one.

A single authority silently imposes its own angle and the pipeline
cannot see that it has done so. Two angles make the difference
visible. That is the whole reason for resolution over mapping.

NOTE ON `may_treat` SCOPE: MED-RT's may_treat is broader than an FDA
approved indication -- it captures therapeutic use, which can include
off-label and class-level use. It also returns some non-indication
DISEASE concepts (e.g. "Drug Hypersensitivity", which is a
contraindication artifact). So it is a CORROBORATING source, not a
replacement for the label. Treat a may_treat-only condition with lower
confidence than one both routes support.

INPUT:  fda_data/openfda_indications.csv (must exist -- run
        download_openfda_indications.py first)
OUTPUT: fda_data/rxnorm_indications.csv

RxNav is a live NLM API with no bulk download and no key required.
This script dedupes rxcuis before calling (many applications share an
ingredient) and pauses between calls. Do not remove the pause.
"""

import csv
import json
import os
import time
import urllib.error
import urllib.request

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
INPUT_FILE = os.path.join(DATA_DIR, "openfda_indications.csv")
OUTPUT_FILE = os.path.join(DATA_DIR, "rxnorm_indications.csv")

RXCLASS_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json"
REQUEST_PAUSE_SECONDS = 0.25
REQUEST_TIMEOUT_SECONDS = 30

OUTPUT_COLUMNS = [
    "rxcui",
    "status",
    "mesh_id",
    "mesh_label",
]


def load_rxcuis(path: str) -> list[str]:
    """Distinct rxcuis from the openFDA pull. Many apps share one."""
    seen = set()
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("rxcui") or "").strip()
            if not raw:
                continue
            for code in raw.split("|"):
                code = code.strip()
                if code:
                    seen.add(code)
    return sorted(seen)


def fetch_may_treat(rxcui: str) -> list[dict]:
    """Return may_treat DISEASE concepts for one rxcui."""
    url = (f"{RXCLASS_URL}?rxcui={rxcui}"
           f"&relaSource=MEDRT&rela=may_treat")
    rows = []
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "fda-recon/1.0"})
        with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        return [{"rxcui": rxcui, "status": f"HTTP_{exc.code}",
                 "mesh_id": "", "mesh_label": ""}]
    except Exception as exc:  # noqa: BLE001
        return [{"rxcui": rxcui, "status": f"ERROR:{type(exc).__name__}",
                 "mesh_id": "", "mesh_label": ""}]

    info = payload.get("rxclassDrugInfoList") or {}
    seen = set()
    for item in info.get("rxclassDrugInfo", []):
        concept = item.get("rxclassMinConceptItem", {})
        if concept.get("classType") != "DISEASE":
            continue
        mesh_id = concept.get("classId", "")
        if not mesh_id or mesh_id in seen:
            continue
        seen.add(mesh_id)
        rows.append({
            "rxcui": rxcui,
            "status": "OK",
            "mesh_id": mesh_id,
            "mesh_label": concept.get("className", ""),
        })

    if not rows:
        rows.append({"rxcui": rxcui, "status": "NO_MAY_TREAT",
                     "mesh_id": "", "mesh_label": ""})
    return rows


def main() -> None:
    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: {INPUT_FILE} not found.")
        print("Run download_openfda_indications.py first -- this script "
              "reads the rxcuis it produces.")
        return

    rxcuis = load_rxcuis(INPUT_FILE)
    total = len(rxcuis)
    print(f"Found {total} distinct rxcuis in the openFDA pull.")

    rows = []
    with_disease = 0
    for position, rxcui in enumerate(rxcuis, start=1):
        results = fetch_may_treat(rxcui)
        rows.extend(results)
        if any(r["status"] == "OK" for r in results):
            with_disease += 1
        if position % 100 == 0 or position == total:
            print(f"  {position}/{total} "
                  f"({with_disease} with a coded indication)")
        time.sleep(REQUEST_PAUSE_SECONDS)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")
    print(f"  rxcuis with >=1 coded indication: {with_disease}/{total}")
    print("Join back to MONDO on mesh_id (mondo_resolution_index.csv "
          "column xref_mesh).")


if __name__ == "__main__":
    main()
