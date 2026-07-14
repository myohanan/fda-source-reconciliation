"""
endpoint_lookup.py
------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Given a DRUG, what did its trials register as outcome measures?

One job. It retrieves. It does not interpret.

It does not know what a COA is. It does not decide whether a registered
endpoint names a qualified instrument -- that is instrument_matcher's
job, and it is the only place that determination is made. It does not
generate a compendium. It hands a sealed list of registered outcomes to
whatever asked, and stops.

WHY THIS LAYER EXISTS

FDA has four sources for drug development tools. Not one of them can
answer whether a qualified COA has ever been used.

  The DDT portal knows a COA was qualified.
  Drugs@FDA knows a drug was approved.
  Nothing connects them.

The COA Compendium was the only thing that ever linked a disease to an
endpoint to the drug approved using it -- and it is a hand-typed PDF,
published June 2021, never reissued. 199 rows.

So FDA cannot measure whether its own qualification program works.

The trial registry can. Sponsors are REQUIRED to declare their primary
and secondary outcome measures before the trial runs. That declaration
is timestamped, structured, and public. It is the authority on what a
trial measured, in exactly the way the trial registry is the authority
on trial populations -- because its purpose requires the record to
exist.

WHAT THIS TOOL DOES NOT CLAIM

It reports the outcome measures a sponsor REGISTERED. It does not claim
those endpoints supported the approval, and it does not claim they name
any particular instrument.

That restraint is not decorative. It was earned:

    Tezspire (tezepelumab) was approved for asthma in December 2021.
    FDA has a QUALIFIED asthma COA -- DDT COA #000006, the Asthma
    Daytime Symptom Diary (ADSD) and Asthma Nighttime Symptom Diary
    (ANSD), six items, scored 0 to 10, developed by C-Path's PRO
    Consortium.

    NAVIGATOR, tezepelumab's pivotal Phase 3, registered as a key
    secondary endpoint: "Mean Change From Baseline at Week 52 in
    Asthma Symptom Diary."

    It is NOT the qualified COA. The ASD used in NAVIGATOR is a
    DIFFERENT instrument -- ten items, scored 0 to 4, from Globe et al
    2015. Different developer, different item count, different scale.

    A string matcher would have called it a hit. It looks like a hit.
    It reads like a hit. It is wrong -- and nobody reviewing the output
    would have caught it, because nothing about it looks broken.

That is the plausible-but-unearned failure this architecture exists to
prevent, and it does not require a model call to occur. So this tool
RETRIEVES and stops. Whether an endpoint names an instrument is a
separate determination, made by a separate tool, which defaults to
HUMAN_REVIEW_REQUIRED.

ARCHITECTURE (ported from clinicaltrials_agent.py in the rare-disease
library, adapted from condition search to INTERVENTION search)
  - retrieves ALL trials with no arbitrary limit, via pagination
  - deduplicates by NCT ID before counting
  - reconciles the DISTINCT retrieved count against the API-reported
    total; an incomplete retrieval is an ERROR, not a shrug
  - validates NCT ID format before accepting a record
  - retrieves primary AND secondary outcomes
  - records the retrieval date for the audit trail
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

CTGOV_URL = "https://clinicaltrials.gov/api/v2/studies"
PAGE_SIZE = 100
SLEEP_SECONDS = 0.35
MAX_RETRIES = 3
TIMEOUT_SECONDS = 60

FIELDS = (
    "NCTId,BriefTitle,OverallStatus,Phase,StartDate,"
    "LeadSponsorName,Condition,"
    "PrimaryOutcomeMeasure,SecondaryOutcomeMeasure"
)

STATUS_OK = "OK"
STATUS_INCOMPLETE = "INCOMPLETE_RETRIEVAL"
STATUS_ERROR = "RETRIEVAL_ERROR"
STATUS_NONE = "NO_TRIALS"

_NCT_RE = re.compile(r"^NCT\d{8}$")


def _valid_nct(nct_id: str) -> bool:
    """NCT followed by exactly 8 digits. A malformed ID corrupts the
    audit trail, so it is rejected rather than carried."""
    return bool(_NCT_RE.match(str(nct_id)))


def _fetch_page(drug: str, page_token: str | None) -> dict:
    """One page of trials for a drug, with retry and backoff."""
    params = {
        "query.intr": drug,
        "pageSize": PAGE_SIZE,
        "fields": FIELDS,
        # WITHOUT THIS, THE API RETURNS NO TOTAL, AND THE
        # RECONCILIATION BELOW SILENTLY DOES NOT RUN. A first version
        # omitted it: the tool would have returned 40 of 200 trials and
        # reported OK, and every downstream count would have been wrong
        # with no way to tell. The check that catches an incomplete
        # retrieval is worthless if the number it checks against is
        # never requested.
        "countTotal": "true",
    }
    if page_token:
        params["pageToken"] = page_token

    url = f"{CTGOV_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "fda-recon/1.0"})

    last_error = ""
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(
                    request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(last_error)


def _parse_study(study: dict) -> dict | None:
    """One study -> a flat record. Returns None if the NCT ID is bad."""
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})

    nct_id = str(identification.get("nctId", "")).strip()
    if not _valid_nct(nct_id):
        return None

    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {})
    outcomes = protocol.get("outcomesModule", {})
    conditions = protocol.get("conditionsModule", {})

    primary = [
        o.get("measure", "").strip()
        for o in outcomes.get("primaryOutcomes", [])
        if o.get("measure")
    ]
    secondary = [
        o.get("measure", "").strip()
        for o in outcomes.get("secondaryOutcomes", [])
        if o.get("measure")
    ]

    return {
        "nct_id": nct_id,
        "title": identification.get("briefTitle", ""),
        "status": status.get("overallStatus", ""),
        "phases": design.get("phases", []),
        "start_date": (status.get("startDateStruct", {})
                       .get("date", "")),
        "sponsor": (sponsor.get("leadSponsor", {})
                    .get("name", "")),
        "conditions": conditions.get("conditions", []),
        "primary_endpoints": primary,
        "secondary_endpoints": secondary,
    }


def lookup(drug: str) -> dict:
    """
    Every trial registered for this drug, and what each measured.

    Sealed. The caller does not re-derive it, and this tool does not
    interpret it.
    """
    if not drug or not drug.strip():
        return _result(drug, STATUS_ERROR, error="EMPTY_DRUG_NAME")

    seen: set[str] = set()
    trials: list[dict] = []
    reported_total = None
    page_token = None
    malformed = 0

    while True:
        try:
            payload = _fetch_page(drug, page_token)
        except Exception as exc:  # noqa: BLE001
            return _result(drug, STATUS_ERROR, error=str(exc)[:120],
                           trials=trials)

        if reported_total is None:
            reported_total = payload.get("totalCount")

        studies = payload.get("studies", [])
        for study in studies:
            record = _parse_study(study)
            if record is None:
                malformed += 1
                continue
            if record["nct_id"] in seen:
                continue
            seen.add(record["nct_id"])
            trials.append(record)

        page_token = payload.get("nextPageToken")
        if not page_token:
            break
        time.sleep(SLEEP_SECONDS)

    if not trials:
        return _result(drug, STATUS_NONE, reported_total=reported_total)

    # RECONCILIATION. An incomplete retrieval is an ERROR, not a shrug.
    # Silently returning 40 of 200 trials would look exactly like a drug
    # that has 40 trials -- and every downstream count would be wrong
    # with no way to tell.
    status = STATUS_OK
    if reported_total is None:
        # The registry did not report a total, so completeness CANNOT
        # be verified. That is not OK -- it is unknown, and saying OK
        # would assert a guarantee the data does not support.
        status = STATUS_INCOMPLETE
    elif len(trials) < reported_total:
        status = STATUS_INCOMPLETE

    return _result(drug, status, trials=trials,
                   reported_total=reported_total, malformed=malformed)


def _result(drug: str, status: str, **kwargs) -> dict:
    trials = kwargs.get("trials", [])
    return {
        "drug": drug,
        "status": status,
        "retrieved": len(trials),
        "reported_total": kwargs.get("reported_total"),
        "malformed_nct_ids": kwargs.get("malformed", 0),
        "trials": trials,
        "error": kwargs.get("error", ""),
        "retrieval_date": date.today().isoformat(),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python3 endpoint_lookup.py "drug name"')
        return

    for drug in sys.argv[1:]:
        result = lookup(drug)
        print()
        print(f'DRUG: "{result["drug"]}"')
        print(f'  status        : {result["status"]}')
        print(f'  trials        : {result["retrieved"]} '
              f'(registry reports {result["reported_total"]})')
        if result["error"]:
            print(f'  ERROR         : {result["error"]}')
        if result["malformed_nct_ids"]:
            print(f'  malformed IDs : {result["malformed_nct_ids"]}')
        print()

        # phase 3 first -- those are the ones that support approval
        def phase_rank(trial):
            phases = trial["phases"]
            if "PHASE3" in phases:
                return 0
            if "PHASE2" in phases:
                return 1
            return 2

        for trial in sorted(result["trials"], key=phase_rank)[:6]:
            phases = "/".join(p.replace("PHASE", "Ph")
                              for p in trial["phases"]) or "-"
            print(f'  {trial["nct_id"]}  [{phases}]  '
                  f'{trial["title"][:52]}')
            for endpoint in trial["primary_endpoints"]:
                print(f'      PRIMARY   {endpoint[:76]}')
            for endpoint in trial["secondary_endpoints"][:8]:
                print(f'      secondary {endpoint[:76]}')
            extra = len(trial["secondary_endpoints"]) - 8
            if extra > 0:
                print(f'      secondary ... and {extra} more')
            print()


if __name__ == "__main__":
    main()
