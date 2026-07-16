"""
trial_instruments.py
--------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

For a disease, what did its approved drugs' trials actually MEASURE?

WHAT THIS ANSWERS

coa_lookup answers "what COAs did FDA qualify for this disease." This
answers a different question: when the approved drugs for this disease
were tested, what outcome measures did their trials actually use -- and
which of those are FDA-qualified COAs, and which are not?

The gap between the two is the finding. A disease can have qualified
COAs that no approval trial used, and approval trials full of
established instruments that were never qualified. This tool makes what
was actually measured visible, and marks each instrument as qualified
or not. It does not judge; it reports.

WHAT IT IS AND IS NOT

It reports CO-OCCURRENCE: an instrument appeared as an outcome measure
in a registered trial of an approved drug for this disease. It does NOT
claim the drug was approved ON that instrument -- a trial names many
outcomes, most of them not the basis of approval. Whether an instrument
was a pivotal endpoint is a regulatory fact in the approval package,
which this tool does not read and does not assert.

The QUALIFIED / NOT-QUALIFIED flag is factual: is this instrument in
FDA's qualified-COA set for this context, or not. It is not a verdict
on the instrument's value. Many excellent, validated instruments are
not formally qualified -- qualification is voluntary.

This is a STANDALONE tool. It consumes a disease name and the qualified-
COA catalog, and returns its own sealed result.
"""

import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CDISC_CSV = os.path.join(_BASE_DIR, "fda_data", "cdisc_instruments.csv")

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
HEADERS = {"User-Agent": "fda-recon/1.0", "Accept": "application/json"}
TIMEOUT = 40
PAUSE = 0.3
PAGE_SIZE = 50
MAX_PAGES_PER_DRUG = 5

# CDISC carries some codes (e.g. CTCAE, MedDRA) whose NAME appears inside
# safety/PK outcome titles that are NOT the instrument being used as a
# clinical measure. A title matching one of these is safety/PK
# scaffolding, not a COA-type instrument, so it is kept out of the
# recognized-instrument bucket. This is a small, explicit list of
# known scaffolding terms -- not a synonym table for instruments.
_SCAFFOLDING = (
    "ctcae", "common terminology criteria", "meddra", "adverse event",
    "adverse events", "pharmacokinetic", "concentration-time",
    "blood pressure", "vital sign",
)

STATUS_FOUND = "INSTRUMENTS_FOUND"
STATUS_NO_TRIALS = "NO_TRIALS_FOUND"
STATUS_NO_DRUGS = "NO_APPROVED_DRUGS"
STATUS_FAILED = "LOOKUP_FAILED"

# An outcome-measure title is often a sentence ("Change from baseline in
# X at week 12"). We want the INSTRUMENT inside it. These are the common
# instrument phrases worth surfacing as distinct measures; the raw
# titles are also kept so nothing is hidden.
_NOISE_PREFIXES = (
    "change from baseline in ", "change in ", "mean change in ",
    "percent change in ", "absolute change in ", "time to ",
    "number of ", "proportion of ", "incidence of ", "rate of ",
)


def _phrase_in(phrase: str, text: str) -> bool:
    """
    True if `phrase` appears in `text` at WORD BOUNDARIES -- so "ess"
    does NOT match inside "assessment", and "6mwt" matches "(6mwt)" but
    a short acronym cannot hide inside a longer word. Both are already
    lowercased and hyphen/space-normalized by the caller.
    """
    if not phrase:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) +
                     r"(?![a-z0-9])", text) is not None


def _clean_measure(title: str) -> str:
    """Trim common outcome-title scaffolding to expose the instrument."""
    low = title.strip()
    changed = True
    while changed:
        changed = False
        for pre in _NOISE_PREFIXES:
            if low.lower().startswith(pre):
                low = low[len(pre):]
                changed = True
    # drop trailing "at week N", "at N weeks", timepoints
    low = re.sub(r"\s+at\s+(week|day|month|year)s?\s*\d+.*$", "", low,
                 flags=re.I)
    low = re.sub(r"\s+at\s+\d+\s+(week|day|month|year)s?.*$", "", low,
                 flags=re.I)
    return low.strip()


def _qualified_index(catalog: dict) -> dict:
    """
    Map lowercased qualified-instrument names (and abbreviations) to
    their catalog label, for matching against trial outcome text. Only
    instruments the catalog marks qualified are included.
    """
    index: dict = {}
    for entries in (catalog or {}).get("by_cui", {}).values():
        for entry in entries or []:
            if not entry.get("qualified"):
                continue
            name = (entry.get("instrument") or "").strip()
            if not name:
                continue
            # the full name
            key = re.sub(r"[-\s]+", " ", name.lower()).strip()
            index[key] = name
            # any (ABBREV) inside the name
            for abbr in re.findall(r"\(([A-Za-z0-9\-]{2,})\)", name):
                index[abbr.lower()] = name
    return index


def _cdisc_index() -> dict:
    """
    Map lowercased CDISC instrument names (and any parenthetical
    abbreviation) to the canonical CDISC name. From cdisc_instruments.csv
    -- the 252 CDISC-recognized clinical instruments (questionnaires,
    functional tests, scales). This is the published authority for "is
    this outcome measure a recognized clinical instrument," the same
    kind of external standard the resolver leans on for identity.
    Returns {} if the file is absent (the CDISC flag then simply does
    not fire; it never falsely says "not an instrument").
    """
    index: dict = {}
    if not os.path.exists(_CDISC_CSV):
        return index
    try:
        with open(_CDISC_CSV, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                name = (row.get("instrument") or "").strip()
                if len(name) < 3:
                    continue
                key = re.sub(r"[-\s]+", " ", name.lower()).strip()
                index[key] = name
                for abbr in re.findall(r"\(([A-Za-z0-9\-]{2,})\)", name):
                    index[abbr.lower()] = name
    except Exception:  # noqa: BLE001
        return {}
    return index


def _fetch(drug: str, cond: str, token: str = "") -> dict:
    params = {
        "query.cond": cond,
        "query.intr": drug,
        "pageSize": PAGE_SIZE,
    }
    if token:
        params["pageToken"] = token
    url = f"{CTGOV}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def _outcomes(study: dict):
    proto = study.get("protocolSection", {})
    om = proto.get("outcomesModule", {})
    for key, kind in (("primaryOutcomes", "primary"),
                      ("secondaryOutcomes", "secondary")):
        for o in om.get(key, []) or []:
            measure = (o.get("measure", "") or "").strip()
            if measure:
                yield kind, measure


def find_instruments(disease: str, drug_generics: list,
                     catalog: dict) -> dict:
    """
    The outcome measures used across the approved drugs' trials for a
    disease, each flagged qualified or not, with primary/secondary and
    a trial count.

    drug_generics: the disease's approved-drug generic names (from
        drug_lookup, deduplicated).
    """
    if not drug_generics:
        return {"status": STATUS_NO_DRUGS, "disease": disease,
                "instruments": [], "n_trials": 0}

    qualified = _qualified_index(catalog)
    cdisc = _cdisc_index()

    # measure -> record with trial-id sets and classification.
    measures: dict = {}
    seen_trials: set = set()

    try:
        for drug in drug_generics:
            token = ""
            pages = 0
            while pages < MAX_PAGES_PER_DRUG:
                payload = _fetch(drug, disease, token)
                for study in payload.get("studies", []) or []:
                    nct = (study.get("protocolSection", {})
                           .get("identificationModule", {})
                           .get("nctId", ""))
                    if nct in seen_trials:
                        continue
                    seen_trials.add(nct)
                    for kind, raw in _outcomes(study):
                        name = _clean_measure(raw)
                        if len(name) < 3:
                            continue
                        # Normalize hyphens and runs of whitespace so
                        # "Six-minute Walk" matches CDISC "Six Minute
                        # Walk". Purely lexical -- no synonyms.
                        low = re.sub(r"[-\s]+", " ", name.lower()).strip()
                        # 1) qualified COA? 2) else CDISC-recognized
                        # instrument? 3) else "other" (PK/safety/lab/
                        # biomarker -- not a recognized COA-type
                        # instrument). Each check is factual containment
                        # against a published list; no interpretation.
                        q_as = ""
                        for q_low, q_label in qualified.items():
                            if _phrase_in(q_low, low):
                                q_as = q_label
                                break
                        c_as = ""
                        is_scaffold = any(s in low for s in _SCAFFOLDING)
                        if not q_as and not is_scaffold:
                            for c_low, c_label in cdisc.items():
                                if _phrase_in(c_low, low):
                                    c_as = c_label
                                    break
                        if q_as:
                            category = "qualified_coa"
                        elif c_as:
                            category = "cdisc_instrument"
                        else:
                            category = "other"
                        rec = measures.setdefault(
                            name, {"primary": set(), "secondary": set(),
                                   "qualified": bool(q_as),
                                   "qualified_as": q_as,
                                   "cdisc_as": c_as,
                                   "category": category})
                        rec[kind].add(nct)
                token = payload.get("nextPageToken", "")
                pages += 1
                if not token:
                    break
                time.sleep(PAUSE)
            time.sleep(PAUSE)
    except Exception as exc:  # noqa: BLE001
        return {"status": STATUS_FAILED, "disease": disease,
                "error": type(exc).__name__, "instruments": [],
                "n_trials": len(seen_trials)}

    if not measures:
        return {"status": STATUS_NO_TRIALS, "disease": disease,
                "instruments": [], "n_trials": len(seen_trials)}

    # Group by CANONICAL instrument. When a measure matched a qualified
    # COA or a CDISC instrument, that canonical name is the header and
    # every raw phrasing ("NSAA", "NSAA Total Score", "the NSAA score")
    # collapses under it -- the trial count is the union across all
    # phrasings, and the variants are kept as sub-lines. "Other"
    # measures have no canonical form, so each cleaned title stands
    # on its own.
    groups: dict = {}
    for name, rec in measures.items():
        if rec["category"] == "qualified_coa":
            key = rec["qualified_as"]
        elif rec["category"] == "cdisc_instrument":
            key = rec["cdisc_as"]
        else:
            key = name
        g = groups.setdefault(key, {
            "instrument": key, "category": rec["category"],
            "qualified": rec["qualified"],
            "primary": set(), "secondary": set(), "variants": set()})
        g["primary"] |= rec["primary"]
        g["secondary"] |= rec["secondary"]
        if name != key:
            g["variants"].add(name)

    out = []
    for key, g in groups.items():
        out.append({
            "instrument": g["instrument"],
            "category": g["category"],
            "qualified": g["qualified"],
            "as_primary": len(g["primary"]),
            "as_secondary": len(g["secondary"]),
            "trials": len(g["primary"] | g["secondary"]),
            "n_variants": len(g["variants"]),
            "variants": sorted(g["variants"]),
        })
    _rank = {"qualified_coa": 0, "cdisc_instrument": 1, "other": 2}
    out.sort(key=lambda m: (_rank[m["category"]], -m["trials"],
                            m["instrument"].lower()))

    return {
        "status": STATUS_FOUND,
        "disease": disease,
        "n_trials": len(seen_trials),
        "n_instruments": len(out),
        "instruments": out,
    }


def main() -> None:
    import sys
    if len(sys.argv) < 2:
        print('usage: python3 trial_instruments.py "disease" '
              '"drug1" "drug2" ...')
        print('  (drug generics from a drug_lookup run)')
        return
    disease = sys.argv[1]
    generics = sys.argv[2:]
    import coa_lookup as coa
    catalog = coa.load_catalog()
    result = find_instruments(disease, generics, catalog)
    print("=" * 68)
    print(f'DISEASE: {result["disease"]}')
    print(f'STATUS : {result["status"]}')
    if result["status"] != STATUS_FOUND:
        print("=" * 68)
        return
    print(f'{result["n_trials"]} trials searched across '
          f'{len(generics)} approved drugs.')
    print(f'{result["n_instruments"]} distinct outcome measures.')
    print()

    inst = result["instruments"]
    qcoa = [i for i in inst if i["category"] == "qualified_coa"]
    cdisc = [i for i in inst if i["category"] == "cdisc_instrument"]
    other = [i for i in inst if i["category"] == "other"]

    def _line(i):
        var = (f'  [{i["n_variants"]} phrasings]'
               if i.get("n_variants") else "")
        return (f'    {i["instrument"][:52]}  '
                f'({i["trials"]} trials, {i["as_primary"]} primary)'
                f'{var}')

    print(f'FDA-QUALIFIED COAs used ({len(qcoa)}):')
    if not qcoa:
        print('    NONE. No FDA-qualified COA appears as an outcome')
        print('    measure in any trial of this disease\'s approved '
              'drugs.')
    for i in qcoa:
        print(_line(i))
    print()

    print(f'RECOGNIZED CLINICAL INSTRUMENTS used, in CDISC but NOT '
          f'FDA-qualified ({len(cdisc)}):')
    if not cdisc:
        print('    none.')
    for i in cdisc:
        print(_line(i))
    print()

    print(f'OTHER outcome measures ({len(other)}) -- not a recognized '
          f'clinical instrument')
    print('    (pharmacokinetics, safety, labs, biomarkers/surrogates). '
          'Full list:')
    for i in other:
        print(_line(i))
    print("=" * 68)


if __name__ == "__main__":
    main()