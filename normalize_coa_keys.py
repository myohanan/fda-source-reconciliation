"""
normalize_coa_keys.py
---------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Extracts a canonical DDT COA number from each of the three FDA COA
source files so they can be joined on a shared key. Each source spells
the identifier differently:

  ddt_projects.csv       ddtProjectNumber      "DDT-COA-000112"
  coa_submissions.csv    (embedded in text)    "DDT COA #000112: ..."
  qualified_coas.csv     (embedded in text)    "DDT COA #000084: ..."

The canonical form is a 6-digit, zero-padded string, e.g. "000112".
This is a diagnostic script: it reports overlap counts across the three
sources so the real match rate is known before any reconciliation is
built on top of the key.
"""

import csv
import re

COA_NUMBER_RE = re.compile(r"(\d{6})")


def canonical_coa_number(raw: str) -> str | None:
    """Pull the 6-digit COA number out of any of the source formats."""
    if not raw:
        return None
    match = COA_NUMBER_RE.search(raw)
    if not match:
        return None
    return match.group(1)


def load_ddt_projects(path: str) -> dict[str, dict]:
    """Key: canonical COA number -> row, from ddt_projects.csv."""
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = canonical_coa_number(row.get("ddtProjectNumber", ""))
            if key:
                out[key] = row
    return out


def load_coa_text_source(path: str) -> dict[str, dict]:
    """
    Key: canonical COA number -> row, from coa_submissions.csv or
    qualified_coas.csv, where the number is embedded in the
    'DDT COA Number and Instrument Name' field.
    """
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = row.get("DDT COA Number and Instrument Name", "")
            key = canonical_coa_number(raw)
            if key:
                out[key] = row
    return out


def join_report(
    ddt_projects: dict[str, dict],
    coa_submissions: dict[str, dict],
    qualified_coas: dict[str, dict],
) -> None:
    ddt_keys = set(ddt_projects)
    sub_keys = set(coa_submissions)
    qual_keys = set(qualified_coas)

    print(f"ddt_projects.csv:      {len(ddt_keys)} distinct COA numbers")
    print(f"coa_submissions.csv:   {len(sub_keys)} distinct COA numbers")
    print(f"qualified_coas.csv:    {len(qual_keys)} distinct COA numbers")
    print()

    print(f"ddt_projects & coa_submissions overlap: "
          f"{len(ddt_keys & sub_keys)}")
    print(f"ddt_projects & qualified_coas overlap:  "
          f"{len(ddt_keys & qual_keys)}")
    print(f"coa_submissions & qualified_coas overlap: "
          f"{len(sub_keys & qual_keys)}")
    print()

    only_in_ddt = ddt_keys - sub_keys - qual_keys
    print(f"In ddt_projects.csv but in neither COA file: "
          f"{len(only_in_ddt)}")
    if only_in_ddt:
        sample = sorted(only_in_ddt)[:10]
        print(f"  sample: {sample}")


if __name__ == "__main__":
    ddt_projects = load_ddt_projects("fda_data/ddt_projects.csv")
    coa_submissions = load_coa_text_source("fda_data/coa_submissions.csv")
    qualified_coas = load_coa_text_source("fda_data/qualified_coas.csv")

    join_report(ddt_projects, coa_submissions, qualified_coas)
