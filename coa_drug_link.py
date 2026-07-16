"""
coa_drug_link.py
----------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Given a COA instrument, which drugs were tested in the trials that used
it as an outcome measure?

WHAT THIS ANSWERS, AND WHAT IT DOES NOT

A clinical trial names both its INTERVENTION (the drug) and its OUTCOME
MEASURES (which may be a COA instrument). So a single trial record links
a drug to a COA directly: this trial tested carvedilol AND used the
KCCQ. This tool reads that link from ClinicalTrials.gov.

It reports CO-OCCURRENCE ONLY: "this drug was tested in trials that used
this COA instrument." It does NOT claim the drug was APPROVED on the
basis of the COA -- trial co-occurrence does not establish that the COA
was a pivotal endpoint in the approval, and the COA may have been a
secondary or exploratory measure. Whether the COA figured in any
approval is a regulatory fact this tool cannot see and does not assert.

It reports DRUGS and BIOLOGICALS only. A COA instrument is used in
device and procedure trials too (the KCCQ appears in tricuspid-valve
device trials); those are not drugs and are excluded.

This is a STANDALONE tool. It does not touch the orchestrator,
endpoint_search, or the drug or COA tools. It consumes a COA instrument
name and returns its own sealed result.
"""

import csv
import json
import os
import time
import urllib.parse
import urllib.request

import drug_resolver as dres

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_INDICATIONS_CSV = os.path.join(
    _BASE_DIR, "fda_data", "openfda_indications.csv")

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
HEADERS = {"User-Agent": "fda-recon/1.0", "Accept": "application/json"}
TIMEOUT = 40
PAUSE = 0.34
PAGE_SIZE = 100
MAX_PAGES = 20

# Intervention types that are a "drug" for this purpose. Devices,
# procedures, behavioral arms, diagnostics are not.
_DRUG_TYPES = frozenset({"DRUG", "BIOLOGICAL"})

# Non-therapy interventions to drop. A trial names its comparator in the
# same intervention list as its investigational drug; placebo, saline,
# sham, and generic control labels are NOT therapies and are excluded.
# NAMED active comparators (e.g. enalapril used as the control arm) are
# KEPT -- a named drug that co-occurred with the COA is a true fact,
# whether it was the investigational arm or the control. This tool
# reports co-occurrence, not which arm a drug was in, so it does not try
# to distinguish subject from comparator; it only removes interventions
# that are not drugs at all.
_CONTROL_TERMS = (
    "placebo",
    "saline",
    "sodium chloride",
    "sham",
    "standard of care",
    "standard therapy",
    "usual care",
    "best supportive care",
    "supportive care",
    "no intervention",
    "observation",
    "vehicle",
    "matching placebo",
    "optimal medical therapy",
    "optimal medical treatment",
    "control rx",
    "control arm",
    "guideline-directed medical therapy",
    "guideline directed medical therapy",
)


def _is_control(name: str) -> bool:
    """True if the intervention is a non-therapy control, not a drug."""
    low = name.lower()
    return any(term in low for term in _CONTROL_TERMS)


def load_approved_ingredients() -> set:
    """
    The set of FDA-APPROVED drug ingredient rxcuis, from openFDA.

    A drug is in openfda_indications.csv because it has an APPROVED
    FDA label with an indication -- presence is the approval signal.
    Each application's rxcuis are resolved UP to their ingredient (the
    same tty=IN normalization drug_resolver uses), so the approved set
    is at the same INGREDIENT level the COA-trial drugs resolve to.
    Matching product rxcuis against ingredient rxcuis directly would
    miss approved drugs on a level mismatch; normalizing both sides to
    ingredient removes that.

    Returns the set of approved ingredient rxcuis. Returns None -- NOT
    an empty set -- if the source cannot be loaded, so the caller can
    tell "no approved match" (a finding) from "could not check
    approval" (a system state). An empty set would silently drop every
    drug as unapproved; None degrades the filter to UNKNOWN instead.
    """
    if not os.path.exists(_INDICATIONS_CSV):
        return None
    try:
        approved: set = set()
        with open(_INDICATIONS_CSV, newline="",
                  encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("status") != "OK":
                    continue
                for rxcui in (row.get("rxcui") or "").split("|"):
                    rxcui = rxcui.strip()
                    if not rxcui:
                        continue
                    for irx in dres.ingredient_rxcuis_of(rxcui):
                        approved.add(irx)
        return approved or None
    except Exception:  # noqa: BLE001
        return None


STATUS_LINKED = "DRUGS_LINKED"
STATUS_NO_DRUGS = "NO_DRUGS_IN_COA_TRIALS"
STATUS_NO_TRIALS = "NO_TRIALS_FOUND"
STATUS_LOOKUP_FAILED = "LOOKUP_FAILED"


def _fetch_page(instrument: str, token: str = "") -> dict:
    params = {
        "query.term": f'"{instrument}"',
        "pageSize": PAGE_SIZE,
    }
    if token:
        params["pageToken"] = token
    url = f"{CTGOV}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def _uses_instrument(study: dict, needle: str) -> bool:
    """
    True only if the instrument appears in an OUTCOME MEASURE title --
    not merely anywhere in the record. The free-text term query is a
    net; this is the confirmation, the same discipline endpoint_search
    uses: the instrument must be an outcome, not an incidental mention.
    """
    proto = study.get("protocolSection", {})
    outcomes = proto.get("outcomesModule", {})
    for key in ("primaryOutcomes", "secondaryOutcomes",
                "otherOutcomes"):
        for om in outcomes.get(key, []) or []:
            if needle in (om.get("measure", "") or "").lower():
                return True
    return False


def _drugs_in(study: dict) -> list[str]:
    """DRUG/BIOLOGICAL intervention names in one study."""
    proto = study.get("protocolSection", {})
    arms = proto.get("armsInterventionsModule", {})
    out = []
    for iv in arms.get("interventions", []) or []:
        if (iv.get("type", "") or "").upper() in _DRUG_TYPES:
            name = (iv.get("name", "") or "").strip()
            if name and not _is_control(name):
                out.append(name)
    return out


def link(instrument: str, approved_only: bool = True) -> dict:
    """
    Drugs tested in trials that used this COA instrument as an outcome.

    Returns a sealed result: each drug with the number of COA-using
    trials it appeared in. Co-occurrence only -- never a claim that the
    COA drove any approval.

    approved_only: when True (the default), the result is filtered to
    FDA-APPROVED drugs -- those whose ingredient is in openFDA's
    approved-label set. Investigational and discontinued compounds are
    dropped: "this COA was used in trials of APPROVED drugs" is the
    finding. If the approved set cannot be loaded, approval status is
    UNKNOWN and NO filtering is applied (every drug is kept), never a
    silent drop of all drugs as unapproved -- the result records
    approval_filter as "UNKNOWN" so the caller sees the filter did not
    run.
    """
    if not instrument:
        return {"status": STATUS_NO_TRIALS, "instrument": instrument,
                "drugs": [], "n_trials": 0}

    approved = load_approved_ingredients() if approved_only else None
    approval_filter = "APPLIED" if approved is not None else (
        "UNKNOWN" if approved_only else "OFF")

    needle = instrument.lower()
    drug_trials: dict[str, int] = {}
    n_trials_using = 0
    token = ""
    pages = 0

    try:
        while pages < MAX_PAGES:
            payload = _fetch_page(instrument, token)
            studies = payload.get("studies", []) or []
            for study in studies:
                if not _uses_instrument(study, needle):
                    continue
                raw_drugs = _drugs_in(study)
                if not raw_drugs:
                    continue
                # Resolve each intervention string to a canonical drug
                # ingredient. Fragments collapse; non-drugs (controls)
                # drop out because they do not resolve; investigational
                # codes not in RxNorm are KEPT under their own name,
                # labeled, so a real drug is never silently lost.
                canon = set()
                for name in set(raw_drugs):
                    r = dres.resolve(name)
                    if r["status"] == dres.STATUS_RESOLVED:
                        # Approved-only: keep only if the ingredient is
                        # in openFDA's approved-label set. A combination
                        # rxcui is "a/b"; every component must be
                        # approved for the combination to count.
                        if approved is not None:
                            comps = r["ingredient_rxcui"].split("/")
                            if not all(c in approved for c in comps):
                                continue
                        canon.add((r["ingredient"],
                                   r["ingredient_rxcui"], False))
                    elif r["status"] == dres.STATUS_NOT_IN_RXNORM:
                        # Not in RxNorm -> not an approved-label drug.
                        # Under approved-only, drop it; otherwise keep
                        # it labeled.
                        if approved is None:
                            canon.add((name, "", True))
                    # NOT_A_DRUG: dropped, it is not a drug
                if not canon:
                    continue
                n_trials_using += 1
                for key in canon:
                    drug_trials[key] = drug_trials.get(key, 0) + 1
            token = payload.get("nextPageToken", "")
            pages += 1
            if not token:
                break
            time.sleep(PAUSE)
    except Exception as exc:  # noqa: BLE001
        return {"status": STATUS_LOOKUP_FAILED,
                "instrument": instrument,
                "error": type(exc).__name__, "drugs": [], "n_trials": 0}

    if not drug_trials:
        status = STATUS_NO_DRUGS if n_trials_using == 0 \
            else STATUS_NO_DRUGS
        return {"status": status, "instrument": instrument,
                "drugs": [], "n_trials": n_trials_using}

    drugs = [{"drug": key[0], "rxcui": key[1],
              "in_rxnorm": not key[2], "trials": count}
             for key, count in drug_trials.items()]
    drugs.sort(key=lambda d: (-d["trials"], d["drug"].lower()))

    return {
        "status": STATUS_LINKED,
        "instrument": instrument,
        "approval_filter": approval_filter,
        "n_trials": n_trials_using,
        "drugs": drugs,
    }


def main() -> None:
    import sys
    if len(sys.argv) < 2:
        print('usage: python3 coa_drug_link.py "COA instrument name"')
        print('  e.g. python3 coa_drug_link.py '
              '"Kansas City Cardiomyopathy Questionnaire"')
        return

    instrument = sys.argv[1]
    print(f'Searching ClinicalTrials.gov for trials that used '
          f'"{instrument}"')
    print('as an outcome measure, and the drugs they tested...')
    print()

    result = link(instrument)

    print("=" * 68)
    print(f'COA INSTRUMENT: {result["instrument"]}')
    print(f'STATUS: {result["status"]}')
    if result["status"] == STATUS_LINKED:
        af = result.get("approval_filter", "OFF")
        if af == "APPLIED":
            print('Filtered to FDA-APPROVED drugs (openFDA approved-'
                  'label set).')
        elif af == "UNKNOWN":
            print('WARNING: the approved-drug set could not be loaded, '
                  'so approval')
            print('filtering did NOT run. The list below is ALL drugs, '
                  'approved or')
            print('not -- this is a system state, not a finding. '
                  'Investigate the')
            print('openFDA indications file before trusting the list.')
        print(f'{result["n_trials"]} trials used this instrument AND '
              f'tested a drug.')
        print(f'{len(result["drugs"])} distinct drugs.')
        print()
        print('These drugs were tested in trials that used this COA as')
        print('an outcome measure. This is CO-OCCURRENCE. It does NOT')
        print('claim the drug was approved on the basis of this COA, or')
        print('that the COA was a pivotal endpoint -- it may have been a')
        print('secondary or exploratory measure. Whether the COA figured')
        print('in any approval is a regulatory fact this tool cannot see')
        print('and does not assert.')
        print()
        print(f'  {"trials":>6}  drug')
        print(f'  {"-"*6}  {"-"*40}')
        for d in result["drugs"]:
            flag = "" if d.get("in_rxnorm", True) \
                else "  [not in RxNorm -- investigational]"
            print(f'  {d["trials"]:>6}  {d["drug"]}{flag}')
    elif result["status"] == STATUS_LOOKUP_FAILED:
        print(f'The lookup failed ({result.get("error", "")}). This is a')
        print('statement about the system, not about the instrument.')
    else:
        print('No drugs were found in trials that used this instrument.')
    print("=" * 68)


if __name__ == "__main__":
    main()