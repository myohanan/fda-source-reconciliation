"""
drug_lookup.py
--------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Given a RESOLVED condition, what drugs has FDA approved for it?

One job. It does not resolve identity -- condition_resolver did that and
sealed it. It does not look at COAs. It does not judge whether a drug is
appropriate for anyone.

TWO ROUTES, NEVER BLENDED

Drugs@FDA has no disease field. It is keyed on ApplNo. So the bridge to
a condition must be built, and there are exactly two ways to build it
from public data. They are NOT a primary and a backup. They answer
DIFFERENT questions, and the object records which one found each drug.

  ROUTE 1 -- CODED (rxnorm_may_treat)
      ApplNo -> rxcui -> MED-RT may_treat -> MeSH -> the condition's CUI

      Fully coded. No text is read at any step. This is the route to
      trust.

      Its scope is BROADER than an approved indication: MED-RT's
      may_treat captures therapeutic use, including off-label and
      class-level use, and it returns some non-indication artifacts
      (aripiprazole may_treat "Drug Hypersensitivity" -- a
      contraindication, not an indication). So a may_treat link is
      evidence of therapeutic association, NOT of an approved
      indication.

  ROUTE 2 -- PROSE (openfda_indication)
      ApplNo -> openFDA indications_and_usage -> match the condition's
      NAME in free text

      This is the APPROVED LABEL. It is the regulatory truth about what
      a drug is indicated for. But it is prose, with no code, so the
      match is a STRING MATCH -- and that is the one place in this tool
      where a silent false positive can enter.

      Guarded by term_match_util's whole-word rule for short terms. But
      that guard protects SHORT terms only. A long term still matches as
      a substring, and "hip fracture" WILL match "chip fracture of the
      talus." That hazard is real; it was encountered in this repository
      while searching ICD-10.

      So every prose match is LABELED as text-derived, and the count is
      never merged with the coded count. A reader can always see which
      route produced a drug.

AGREEMENT IS CORROBORATION. DISAGREEMENT IS A FINDING.

A drug found by BOTH routes is strongly supported: the label says it and
the coded therapeutic classification says it. A drug found by only one
is weaker evidence, and the object says which one -- rather than
flattening both into a confidence number that no auditor could walk back
to its cause.

INPUTS (all on disk, all produced by committed scripts)
  fda_data/openfda_indications.csv   ApplNo -> indication prose, rxcui
  fda_data/rxnorm_indications.csv    rxcui  -> MeSH-coded conditions
  fda_data/drugsatfda/Submissions.txt  ApplNo -> original approval date
"""

import csv
import os
import sys
from collections import defaultdict

import condition_resolver as cr
import term_match_util as tm

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")

INDICATIONS_CSV = os.path.join(DATA_DIR, "openfda_indications.csv")
RXNORM_CSV = os.path.join(DATA_DIR, "rxnorm_indications.csv")
SUBMISSIONS_TXT = os.path.join(DATA_DIR, "drugsatfda", "Submissions.txt")

ROUTE_CODED = "rxnorm_may_treat"
ROUTE_PROSE = "openfda_indication"

STATUS_FOUND = "DRUGS_FOUND"
STATUS_NONE = "NO_DRUGS"
STATUS_UNRESOLVED = "CONDITION_UNRESOLVED"

_mesh_cache: dict[str, set[str]] = {}

# The minimum a prose match needs to be worth attempting. A very short
# condition name ("Pain", "Itch") matched against thousands of label
# paragraphs produces noise, and term_match_util's word-boundary guard
# protects short terms but cannot make them specific.
PROSE_MIN_TERM_LENGTH = 6


def load_approvals() -> dict:
    """ApplNo -> earliest ORIGINAL approval date."""
    approved: dict[str, str] = {}
    if not os.path.exists(SUBMISSIONS_TXT):
        return approved
    with open(SUBMISSIONS_TXT, newline="", encoding="utf-8",
              errors="ignore") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("SubmissionType") != "ORIG":
                continue
            if row.get("SubmissionStatus") != "AP":
                continue
            appl = (row.get("ApplNo") or "").strip()
            date = (row.get("SubmissionStatusDate") or "")[:10]
            if not appl or not date:
                continue
            if appl not in approved or date < approved[appl]:
                approved[appl] = date
    return approved


def load_drugs() -> dict:
    """
    Every application with an indication, and its rxcuis.

    Also builds rxcui -> MeSH, from the coded route.
    """
    applications: list[dict] = []
    by_rxcui: dict[str, list[dict]] = defaultdict(list)

    with open(INDICATIONS_CSV, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["status"] != "OK":
                continue
            rxcuis = [c for c in (row["rxcui"] or "").split("|") if c]
            record = {
                "appl_no": row["ApplNo"],
                "appl_type": row["ApplType"],
                "brand": row["brand_name"],
                "generic": row["generic_name"],
                "indication": row["indication_text"],
                "rxcuis": rxcuis,
                "pharm_class": row["pharm_class"],
            }
            applications.append(record)
            for rxcui in rxcuis:
                by_rxcui[rxcui].append(record)

    # rxcui -> the MeSH-coded conditions MED-RT says it may treat
    mesh_by_rxcui: dict[str, set[str]] = defaultdict(set)
    if os.path.exists(RXNORM_CSV):
        with open(RXNORM_CSV, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["status"] != "OK" or not row["mesh_id"]:
                    continue
                mesh_by_rxcui[row["rxcui"]].add(row["mesh_id"])

    return {
        "applications": applications,
        "by_rxcui": by_rxcui,
        "mesh_by_rxcui": mesh_by_rxcui,
    }


def _mesh_ids_for(cui: str) -> set[str]:
    """
    The MeSH descriptors for a resolved condition -- from UMLS itself.

    A first version read MONDO's xref_mesh column, and the coded route
    returned ZERO drugs for breast cancer. The reason:

        MONDO:0007254  breast cancer  ->  xref_mesh: (EMPTY)

    while RxNorm links 826 rxcuis to MeSH D001943 (Breast Neoplasms).
    The data was on disk. The BRIDGE was missing -- and it was missing
    for the most common cancer in American women.

    That is the same MONDO-xref gap already measured in this repository:
    the MeSH-to-MONDO join closes at only 70%, and MONDO's xrefs proved
    unsafe for identity as well (it maps "hip fracture" to a NARROWER
    femoral-neck concept).

    So do not route through MONDO. UMLS IS the metathesaurus -- a CUI
    has MeSH atoms by construction. Ask the authority directly instead
    of asking a peer for its notes on the authority.
    """
    if not cui or not cr.UMLS_API_KEY:
        return set()

    cached = _mesh_cache.get(cui)
    if cached is not None:
        return cached

    ids: set[str] = set()
    try:
        atoms = cr._umls_get(
            f"/content/current/CUI/{cui}/atoms",
            sabs="MSH", pageSize=50)["result"]
        for atom in atoms:
            raw = atom.get("code", "")
            if raw:
                code = raw.rstrip("/").split("/")[-1]
                if code.startswith("D") or code.startswith("C"):
                    ids.add(code)
    except Exception:  # noqa: BLE001
        pass

    _mesh_cache[cui] = ids
    return ids


def lookup(resolved: dict, drugs: dict, approvals: dict) -> dict:
    """
    Drugs FDA approved for this condition -- by two independent routes,
    each labeled, never blended.
    """
    if not resolved.get("cui"):
        return {
            "query": resolved.get("query", ""),
            "status": STATUS_UNRESOLVED,
            "cui": "",
            "label": "",
            "drugs": [],
            "note": (f'The condition did not resolve to a concept '
                     f'({resolved.get("status", "")}). No lookup is '
                     f'possible. This is NOT a statement that FDA has '
                     f'approved no drugs -- it is a statement that we '
                     f'could not determine what disease this is.'),
        }

    cui = resolved["cui"]
    label = resolved.get("label", "")

    found: dict[str, dict] = {}

    # --- ROUTE 1: CODED. No text is read.
    mesh_ids = _mesh_ids_for(cui)
    if mesh_ids:
        for rxcui, mesh_set in drugs["mesh_by_rxcui"].items():
            if not (mesh_set & mesh_ids):
                continue
            for record in drugs["by_rxcui"].get(rxcui, []):
                key = record["appl_no"]
                entry = found.setdefault(key, {**record, "routes": []})
                if ROUTE_CODED not in entry["routes"]:
                    entry["routes"].append(ROUTE_CODED)

    # --- ROUTE 2: PROSE. The approved label -- but a string match.
    terms = [label] if label else []
    terms.append(resolved.get("query", ""))
    terms = [t.lower().strip() for t in terms
             if t and len(t.strip()) >= PROSE_MIN_TERM_LENGTH]

    if terms:
        for record in drugs["applications"]:
            text = record["indication"].lower()
            for term in terms:
                if tm.term_matches(term, text):
                    key = record["appl_no"]
                    entry = found.setdefault(
                        key, {**record, "routes": []})
                    if ROUTE_PROSE not in entry["routes"]:
                        entry["routes"].append(ROUTE_PROSE)
                    break

    if not found:
        return {
            "query": resolved["query"],
            "status": STATUS_NONE,
            "cui": cui,
            "label": label,
            "drugs": [],
            "note": (f'Resolved to {cui} ({label}). Neither the coded '
                     f'route (RxNorm may_treat) nor the approved-label '
                     f'route (openFDA indication text) returned a drug '
                     f'for this condition.'),
        }

    drug_list = []
    for record in found.values():
        drug_list.append({
            "appl": f'{record["appl_type"]}{record["appl_no"]}',
            "brand": record["brand"],
            "generic": record["generic"],
            "pharm_class": record["pharm_class"],
            "approved": approvals.get(record["appl_no"], ""),
            "routes": sorted(record["routes"]),
            "both_routes": len(record["routes"]) == 2,
            "indication": record["indication"][:200],
        })

    drug_list.sort(
        key=lambda d: (not d["both_routes"], d["approved"] or "9999"))

    return {
        "query": resolved["query"],
        "status": STATUS_FOUND,
        "cui": cui,
        "label": label,
        "drugs": drug_list,
        "note": "",
    }


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python3 drug_lookup.py "disease name"')
        return

    context = cr.load_sources()
    drugs = load_drugs()
    approvals = load_approvals()

    for name in sys.argv[1:]:
        resolved = cr.resolve(name, context)
        result = lookup(resolved, drugs, approvals)

        print()
        print(f'QUERY: "{result["query"]}"')
        print(f'  resolved : {result["cui"]}  {result["label"]}')
        print(f'  status   : {result["status"]}')
        print()

        if result["status"] != STATUS_FOUND:
            print(f'  {result["note"]}')
            print()
            continue

        both = [d for d in result["drugs"] if d["both_routes"]]
        coded = [d for d in result["drugs"]
                 if d["routes"] == [ROUTE_CODED]]
        prose = [d for d in result["drugs"]
                 if d["routes"] == [ROUTE_PROSE]]

        print(f'  {len(result["drugs"])} drug applications')
        print(f'      BOTH routes agree      : {len(both)}')
        print(f'      coded route only       : {len(coded)}')
        print(f'      approved-label only    : {len(prose)}')
        print()

        if both:
            print('  BOTH ROUTES -- the label says it AND the coded')
            print('  therapeutic classification says it:')
            for drug in both[:8]:
                print(f'      {drug["approved"] or "----------"}  '
                      f'{drug["appl"]:<11} {drug["brand"][:22]:<22} '
                      f'{drug["generic"][:26]}')
            print()

        if prose:
            print('  APPROVED-LABEL ONLY -- text-derived. The label')
            print('  names this condition; the coded route does not')
            print('  link it. A string match, so read the indication:')
            for drug in prose[:5]:
                print(f'      {drug["approved"] or "----------"}  '
                      f'{drug["appl"]:<11} {drug["brand"][:22]:<22} '
                      f'{drug["generic"][:26]}')
                print(f'          "{drug["indication"][:70]}"')
            print()

        if coded:
            print('  CODED ROUTE ONLY -- MED-RT says therapeutic use,')
            print('  but the approved label does not name the')
            print('  condition. may_treat is BROADER than an approved')
            print('  indication:')
            for drug in coded[:5]:
                print(f'      {drug["approved"] or "----------"}  '
                      f'{drug["appl"]:<11} {drug["brand"][:22]:<22} '
                      f'{drug["generic"][:26]}')
            print()


if __name__ == "__main__":
    main()
