"""
extract_coa_compendium.py
-------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Extracts the COA Compendium PDF into a structured CSV.

The Compendium is the one FDA source that already links, by hand, the
four things the other sources keep apart: Disease/Condition, the COA
(concept + tool type + context of use), and the approved Drug + approval
date, grouped under a CDER review division. It is therefore both a
fourth data source AND a partial ground-truth set: the reconciliation
engine's disease-to-COA-to-drug joins can be checked against what FDA
already linked here manually.

The Compendium is a PDF, so extraction is fidelity-critical, not a
neutral conversion. Table cells wrap across lines, a single cell may
list multiple drugs numbered "1. ... 2. ...", and rows can span page
breaks. This script uses pdfplumber table extraction (which preserves
cell boundaries far better than raw text) and writes each row with its
source page number so any value can be traced back and spot-checked
against the PDF. It does NOT attempt to split multi-drug cells or parse
approval dates into structured fields -- that is a downstream decision,
and splitting here would risk silently mis-associating a drug with the
wrong disease. The raw cell text is preserved verbatim for that reason.

Output: fda_data/coa_compendium.csv with columns
  division, disease, context_of_use, concept, coa_tool_type,
  drug_approval, page
"""

import csv
import os

import pdfplumber

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_FILE = os.path.join(_BASE_DIR, "fda_data", "coa_compendium.pdf")
OUTPUT_FILE = os.path.join(_BASE_DIR, "fda_data", "coa_compendium.csv")

OUTPUT_COLUMNS = [
    "division",
    "disease",
    "context_of_use",
    "concept",
    "coa_tool_type",
    "drug_approval",
    "page",
]


def _clean(cell: object) -> str:
    """Flatten a table cell to single-line, stripped text."""
    if cell is None:
        return ""
    return str(cell).replace("\n", " ").strip()


def _is_division_header(cells: list[str]) -> bool:
    """A division/office banner: first cell set, all others empty."""
    if not cells or not cells[0]:
        return False
    if any(cells[1:]):
        return False
    return "DIVISION" in cells[0] or "OFFICE" in cells[0]


def extract_rows(pdf_path: str) -> list[dict]:
    """Extract Compendium data rows, carrying the current division."""
    rows = []
    current_division = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                for raw in table:
                    cells = [_clean(c) for c in raw]

                    if _is_division_header(cells):
                        current_division = cells[0]
                        continue
                    if not cells or not cells[0]:
                        continue
                    if cells[0].startswith("Disease/Condition"):
                        continue
                    if len(cells) < 5:
                        continue

                    rows.append({
                        "division": current_division,
                        "disease": cells[0],
                        "context_of_use": cells[1],
                        "concept": cells[2],
                        "coa_tool_type": cells[3],
                        "drug_approval": cells[4],
                        "page": page_number,
                    })
    return rows


def main() -> None:
    if not os.path.exists(PDF_FILE):
        print(f"ERROR: {PDF_FILE} not found. Confirm the PDF is in "
              f"fda_data/ before running.")
        return

    rows = extract_rows(PDF_FILE)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    with_drug = sum(1 for r in rows if r["drug_approval"])
    divisions = len({r["division"] for r in rows if r["division"]})
    print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")
    print(f"  rows with a drug listed: {with_drug}")
    print(f"  distinct divisions: {divisions}")
    print("NOTE: multi-drug cells and approval dates are left as raw "
          "text on purpose; splitting them is a downstream decision.")


if __name__ == "__main__":
    main()
