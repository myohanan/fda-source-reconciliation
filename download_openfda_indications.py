"""
download_openfda_indications.py
-------------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Bridges Drugs@FDA to a disease/indication anchor.

The local Drugs@FDA tables key on ApplNo and carry NO disease field.
The openFDA drug label API exposes the same drugs, keyed on the same
application number, and additionally returns the indication text and
harmonized coded identifiers (rxcui, unii, pharmacologic class). This
script reads every ApplNo + ApplType from the local Applications.txt,
queries openFDA once per application, and writes the indication text
plus coded anchors to fda_data/openfda_indications.csv.

The indication text is prose (openFDA does not code it to MedDRA or
SNOMED in a structured field), so it still requires name-level handling
downstream. The rxcui / pharm_class fields are the more reliable
anchors and are the recommended join surface for reconciliation.

Coverage is partial by nature: not every ApplNo has a label record in
openFDA (older or discontinued products may be absent), and a missing
record is written with an empty indication and a status column so the
gap is visible rather than silent -- the same detection-only principle
the disease-resolution layer uses for degraded source files.

An openFDA API key is read from .env (OPENFDA_API_KEY) via python-dotenv,
matching config.py's key-handling pattern. With a key the daily request
limit is 120,000 (vs 1,000 unkeyed), enough for a full run over all
applications. If no key is present the script still runs but will hit
the unkeyed limit; it warns once at startup.
"""

import csv
import json
import os
import time
import urllib.parse
import urllib.request

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPLICATIONS_FILE = os.path.join(
    _BASE_DIR, "fda_data", "drugsatfda", "Applications.txt")
OUTPUT_FILE = os.path.join(
    _BASE_DIR, "fda_data", "openfda_indications.csv")

OPENFDA_API_KEY = (os.environ.get("OPENFDA_API_KEY") or "").strip()

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
REQUEST_PAUSE_SECONDS = 0.3
REQUEST_TIMEOUT_SECONDS = 30

OUTPUT_COLUMNS = [
    "ApplNo",
    "ApplType",
    "status",
    "brand_name",
    "generic_name",
    "indication_text",
    "rxcui",
    "unii",
    "pharm_class",
]


def _first(value: object) -> str:
    """openFDA fields are lists; take the first, or empty string."""
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return ""


def _join(value: object) -> str:
    """Join a list field into a pipe-delimited string."""
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    if isinstance(value, str):
        return value
    return ""


def _fetch(appl_no: str, appl_type: str) -> dict:
    """Query openFDA for one application number. Returns a result row."""
    search = f"openfda.application_number:{appl_type}{appl_no}"
    params = {"search": search, "limit": 1}
    if OPENFDA_API_KEY:
        params["api_key"] = OPENFDA_API_KEY
    query = urllib.parse.urlencode(params)
    url = f"{OPENFDA_LABEL_URL}?{query}"
    row = {
        "ApplNo": appl_no,
        "ApplType": appl_type,
        "status": "NOT_FOUND",
        "brand_name": "",
        "generic_name": "",
        "indication_text": "",
        "rxcui": "",
        "unii": "",
        "pharm_class": "",
    }
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "fda-recon/1.0"})
        with urllib.request.urlopen(
                req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
        result = data["results"][0]
        openfda = result.get("openfda", {})
        indication = result.get("indications_and_usage", [])
        row["status"] = "OK"
        row["brand_name"] = _first(openfda.get("brand_name"))
        row["generic_name"] = _first(openfda.get("generic_name"))
        row["indication_text"] = _first(indication).strip()
        row["rxcui"] = _join(openfda.get("rxcui"))
        row["unii"] = _join(openfda.get("unii"))
        row["pharm_class"] = _join(openfda.get("pharm_class_epc"))
    except urllib.error.HTTPError as exc:
        row["status"] = "NOT_FOUND" if exc.code == 404 else f"HTTP_{exc.code}"
    except Exception as exc:  # noqa: BLE001 - record, do not crash the run
        row["status"] = f"ERROR:{type(exc).__name__}"
    return row


def load_applications(path: str) -> list[tuple[str, str]]:
    """Read (ApplNo, ApplType) pairs from Applications.txt (tab-sep)."""
    pairs = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for record in reader:
            appl_no = (record.get("ApplNo") or "").strip()
            appl_type = (record.get("ApplType") or "").strip()
            if appl_no and appl_type:
                pairs.append((appl_no, appl_type))
    return pairs


def main() -> None:
    if not OPENFDA_API_KEY:
        print("WARNING: no OPENFDA_API_KEY found in .env — running "
              "unkeyed (1,000/day limit). A full run will not complete.")

    applications = load_applications(APPLICATIONS_FILE)
    total = len(applications)
    print(f"Loaded {total} applications from Applications.txt")

    rows = []
    ok = 0
    for index, (appl_no, appl_type) in enumerate(applications, start=1):
        row = _fetch(appl_no, appl_type)
        rows.append(row)
        if row["status"] == "OK":
            ok += 1
        if index % 100 == 0 or index == total:
            print(f"  {index}/{total} processed ({ok} matched)")
        time.sleep(REQUEST_PAUSE_SECONDS)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")
    print(f"Matched an openFDA label for {ok}/{total} applications.")


if __name__ == "__main__":
    main()
