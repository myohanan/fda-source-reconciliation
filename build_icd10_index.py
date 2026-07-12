"""
build_icd10_index.py
--------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Pulls the full ICD-10-CM code set as a local index.

ICD-10-CM is a BILLING taxonomy, included as a source of LAST RESORT.
Its weaknesses are recorded here rather than discovered later:

  It does not carry clinical vernacular. A query for "breast cancer"
  returns ZERO results, because ICD-10 calls it "Malignant neoplasm of
  breast." Any resolver leaning on ICD-10 for common disease names will
  fail on the most ordinary queries.

  It splits by billing-relevant distinctions -- laterality, severity,
  acute-on-chronic, "unspecified." A query for "chronic heart failure"
  returns twelve codes, all NARROWER than the query (chronic systolic,
  chronic diastolic, chronic right). A resolver that accepted the top
  hit would silently substitute a SUBTYPE for the parent. That is a
  false identity, and it is the dangerous kind, because it looks right.

  Its cross-reference coverage into MONDO is thin: roughly 2,089
  ICD-10-CM xrefs against 32,095 MONDO classes. Even a successful ICD
  match often has no bridge back to the canonical object.

Why pull it at all: it occasionally carries the exact string no other
source has. "Functional dyspepsia" is ICD-10's own label (K30) and
appears nowhere else as an exact term; SNOMED calls it "Nonulcer
dyspepsia." "Sarcopenia" is an exact label (M62.84).

WHETHER ICD-10 EARNS A PLACE IN THE RESOLVER IS AN OPEN EXPERIMENT.
Plan: build the resolver on MONDO + MeSH + SNOMED, measure against all
54 FDA COA conditions and the 199 Compendium diseases, then add ICD-10
as a final strategy and measure the DELTA. If it rescues cases nothing
else could, it stays -- marked ICD-derived, lower-confidence, and never
allowed to return a subtype as an exact match. If it rescues nothing,
it is dropped with evidence rather than on instinct.

This script exists so the file is on disk BEFORE that experiment.

SOURCE NOTE: NLM's Clinical Table API caps paging at ~7,500 of 74,719
codes, so it cannot produce the full set. This uses the official
CDC/NCHS bulk release instead -- complete, no key, no license.

Codes ship UNDOTTED (A000). This script writes both the raw form and a
dotted form (A00.0), because MONDO's xrefs use the dotted convention
and the join must not fail on punctuation.

PARSING NOTE (a real bug, caught and fixed): the file is FIXED-WIDTH,
not delimited. A first attempt split on two-or-more spaces, which
worked for short codes (A000 + wide padding) but silently dropped every
LONG code -- a 7-character code such as C441021 leaves only a SINGLE
space before its description. That parser reported success and lost
51,178 of 74,260 codes without error. The split is now on any
whitespace run, and the row count is asserted against the line count so
a silent drop cannot recur.

Output: fda_data/icd10cm_index.csv  (code, code_dotted, name)
"""

import csv
import io
import os
import re
import urllib.request
import zipfile

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
OUTPUT_FILE = os.path.join(DATA_DIR, "icd10cm_index.csv")

ICD_ZIP_URL = (
    "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/"
    "ICD10CM/2025/ICD10-CM%20Code%20Descriptions%202025.zip"
)
CODES_MEMBER = "icd10cm-codes-2025.txt"

OUTPUT_COLUMNS = ["code", "code_dotted", "name"]

_SPLIT_RE = re.compile(r"\s+")


def _dotted(code: str) -> str:
    """A000 -> A00.0 ; codes of length <= 3 are unchanged."""
    if len(code) <= 3:
        return code
    return f"{code[:3]}.{code[3:]}"


def build_rows(text: str) -> list[dict]:
    """Parse the fixed-width codes file into rows."""
    rows = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        parts = _SPLIT_RE.split(line, maxsplit=1)
        if len(parts) != 2:
            continue
        code, name = parts[0].strip(), parts[1].strip()
        if not code or not name:
            continue
        rows.append({
            "code": code,
            "code_dotted": _dotted(code),
            "name": name,
        })
    return rows


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    print("Downloading ICD-10-CM code descriptions (CDC/NCHS)...")
    with urllib.request.urlopen(ICD_ZIP_URL, timeout=120) as response:
        payload = response.read()
    print(f"  downloaded {len(payload):,} bytes")

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.endswith(CODES_MEMBER)]
        if not names:
            print(f"ERROR: {CODES_MEMBER} not found in the archive.")
            print(f"  archive contains: {archive.namelist()}")
            return
        with archive.open(names[0]) as handle:
            text = handle.read().decode("utf-8", errors="ignore")

    rows = build_rows(text)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    line_count = sum(
        1 for line in text.splitlines() if line.strip())

    print()
    print(f"Wrote {len(rows)} codes to {OUTPUT_FILE}")
    print(f"  source file non-empty lines: {line_count}")
    if len(rows) != line_count:
        print(f"  WARNING: parsed {len(rows)} of {line_count} lines -- "
              f"{line_count - len(rows)} dropped. Do not use this index.")


if __name__ == "__main__":
    main()
