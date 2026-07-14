"""
endpoint_search.py
------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Given a string that names an instrument, find every trial that
registered it as an outcome measure.

One job. It retrieves. It does not interpret.

It does not know what a COA is. It does not decide whether a returned
outcome actually names the instrument you asked for -- that is
instrument_matcher's determination, and it is the only place that
determination is made. It hands back a sealed list of trials and THE
VERBATIM OUTCOME TEXT it matched, and stops.

WHY THIS LAYER EXISTS

FDA has four sources for drug development tools, and not one of them can
answer whether a qualified COA has ever been used.

    The DDT portal knows a COA was qualified.
    Drugs@FDA knows a drug was approved.
    Nothing connects them.

The COA Compendium was the only thing that ever linked a disease to an
endpoint to the drug approved using it -- a hand-typed PDF, published
June 2021, never reissued, 199 rows. So FDA cannot measure whether its
own qualification program works.

The trial registry can. Sponsors are REQUIRED to declare their primary
and secondary outcome measures before the trial runs. That declaration
is timestamped, structured, and public. It is the authority on what a
trial measured -- because its purpose requires the record to exist.

THE VERBATIM RETURN IS NOT OPTIONAL

This tool returns the EXACT outcome string it matched. Never a boolean.
Never a summary. The verbatim text, as the sponsor registered it.

That is not fastidiousness. It is the only thing that catches this:

    FDA's qualified asthma COA is DDT COA #000006 -- the Asthma
    DAYTIME Symptom Diary (ADSD) and Asthma NIGHTTIME Symptom Diary
    (ANSD). Six items. Scored 0 to 10. Developed by C-Path's PRO
    Consortium.

    NAVIGATOR -- the pivotal Phase 3 that got Tezspire approved --
    registered a key secondary endpoint reading "Change from baseline
    in Asthma Symptom Diary."

    IT IS A DIFFERENT INSTRUMENT. The ASD used in NAVIGATOR is ten
    items, scored 0 to 4, from Globe et al 2015. Different developer,
    different item count, different scale.

    Confirmed by the registry itself: searching the outcome text for
    "Asthma Symptom Diary" returns 22 trials; searching for "Asthma
    Daytime Symptom Diary" returns 8. Different searches, different
    trials. If they were one instrument the searches would collide.

    A boolean "COA used: yes" would have buried that permanently, and
    no reviewer would have caught it, because nothing about the output
    would look broken.

So: the string comes back verbatim, and a separate tool decides what it
means.

SENSITIVITY IS THE POINT HERE

This is the WIDE NET. Searching "Asthma Symptom Diary" will return the
ADSD, the ANSD, the ASD, and anything else whose outcome text contains
those words. That over-return is CORRECT. Specificity is applied
afterward, by instrument_matcher, which defaults to
HUMAN_REVIEW_REQUIRED.

A screen that misses is worthless. A screen that over-returns is doing
its job.

ARCHITECTURE (ported from clinicaltrials_agent.py in the rare-disease
library)
  - retrieves ALL trials with no arbitrary limit, via pagination
  - deduplicates by NCT ID before counting
  - reconciles the DISTINCT retrieved count against the API-reported
    total; an incomplete retrieval is an ERROR, not a shrug -- and if
    the registry reports no total, completeness CANNOT be verified,
    which is also not OK
  - validates NCT ID format before accepting a record
  - records the retrieval date for the audit trail
"""

import json
import re
import sys
import time
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
    "LeadSponsorName,Condition,InterventionName,"
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


def _fetch_page(instrument: str, page_token: str | None) -> dict:
    """One page of trials whose OUTCOME TEXT contains the instrument."""
    params = {
        "query.outc": f'"{instrument}"',
        "pageSize": PAGE_SIZE,
        "fields": FIELDS,
        # Without countTotal, the API returns no total and the
        # reconciliation below silently does not run. A first version of
        # its sibling omitted this: the tool would have returned 40 of
        # 200 trials, reported OK, and every downstream count would have
        # been wrong with no way to tell.
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


def _matching_outcomes(outcomes: list[dict],
                       needle: str) -> list[str]:
    """
    The VERBATIM outcome strings that contain the search term.

    Case-insensitive containment, and nothing more. This is the WIDE
    NET, not the determination. What comes back is the sponsor's own
    words, unaltered, for a human or a downstream tool to judge.
    """
    hits = []
    for outcome in outcomes:
        measure = (outcome.get("measure") or "").strip()
        if measure and needle in measure.lower():
            hits.append(measure)
    return hits


def _parse_study(study: dict, needle: str) -> dict | None:
    """One study -> a flat record. None if the NCT ID is malformed."""
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
    arms = protocol.get("armsInterventionsModule", {})

    primary_hits = _matching_outcomes(
        outcomes.get("primaryOutcomes", []), needle)
    secondary_hits = _matching_outcomes(
        outcomes.get("secondaryOutcomes", []), needle)

    interventions = [
        i.get("name", "")
        for i in arms.get("interventions", [])
        if i.get("name")
    ]

    return {
        "nct_id": nct_id,
        "title": identification.get("briefTitle", ""),
        "status": status.get("overallStatus", ""),
        "phases": design.get("phases", []),
        "start_date": status.get("startDateStruct", {}).get("date", ""),
        "sponsor": sponsor.get("leadSponsor", {}).get("name", ""),
        "conditions": conditions.get("conditions", []),
        "interventions": interventions,
        # VERBATIM. Never a boolean.
        "matched_primary": primary_hits,
        "matched_secondary": secondary_hits,
        "as_primary": bool(primary_hits),
    }


def search(instrument: str) -> dict:
    """
    Every trial that registered this instrument as an outcome measure.

    Sealed. The caller does not re-derive it, and this tool does not
    decide whether the returned text actually names the instrument.
    """
    if not instrument or not instrument.strip():
        return _result(instrument, STATUS_ERROR,
                       error="EMPTY_INSTRUMENT_NAME")

    needle = instrument.strip().lower()
    seen: set[str] = set()
    trials: list[dict] = []
    reported_total = None
    page_token = None
    malformed = 0

    while True:
        try:
            payload = _fetch_page(instrument, page_token)
        except Exception as exc:  # noqa: BLE001
            return _result(instrument, STATUS_ERROR,
                           error=str(exc)[:120], trials=trials)

        if reported_total is None:
            reported_total = payload.get("totalCount")

        for study in payload.get("studies", []):
            record = _parse_study(study, needle)
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
        return _result(instrument, STATUS_NONE,
                       reported_total=reported_total)

    status = STATUS_OK
    if reported_total is None:
        # Completeness CANNOT be verified. That is not OK -- it is
        # unknown, and reporting OK would assert a guarantee the data
        # does not support.
        status = STATUS_INCOMPLETE
    elif len(trials) < reported_total:
        status = STATUS_INCOMPLETE

    return _result(instrument, status, trials=trials,
                   reported_total=reported_total, malformed=malformed)


def _result(instrument: str, status: str, **kwargs) -> dict:
    trials = kwargs.get("trials", [])
    return {
        "instrument": instrument,
        "status": status,
        "retrieved": len(trials),
        "reported_total": kwargs.get("reported_total"),
        "malformed_nct_ids": kwargs.get("malformed", 0),
        "as_primary": sum(1 for t in trials if t["as_primary"]),
        "trials": trials,
        "error": kwargs.get("error", ""),
        "retrieval_date": date.today().isoformat(),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python3 endpoint_search.py "instrument name"')
        return

    for instrument in sys.argv[1:]:
        result = search(instrument)
        print()
        print(f'INSTRUMENT: "{result["instrument"]}"')
        print(f'  status     : {result["status"]}')
        print(f'  trials     : {result["retrieved"]} '
              f'(registry reports {result["reported_total"]})')
        print(f'  as PRIMARY : {result["as_primary"]}')
        if result["error"]:
            print(f'  ERROR      : {result["error"]}')
        print()

        def rank(trial):
            return (0 if trial["as_primary"] else 1,
                    0 if "PHASE3" in trial["phases"] else 1)

        for trial in sorted(result["trials"], key=rank)[:8]:
            phases = "/".join(p.replace("PHASE", "Ph")
                              for p in trial["phases"]) or "-"
            print(f'  {trial["nct_id"]}  [{phases}]  '
                  f'{trial["sponsor"][:28]}')
            print(f'      {trial["title"][:66]}')
            for text in trial["matched_primary"]:
                print(f'      PRIMARY   "{text[:66]}"')
            for text in trial["matched_secondary"][:3]:
                print(f'      secondary "{text[:66]}"')
            print()

        print('  NOTE: the matched text is VERBATIM, as the sponsor')
        print('  registered it. This tool makes NO claim that it names')
        print('  the instrument you searched for. That determination')
        print('  belongs to instrument_matcher.')


if __name__ == "__main__":
    main()
