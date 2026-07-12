"""
build_mesh_index.py
-------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Builds the MeSH disease-term index -- the literature-side resolver.

MONDO models disease IDENTITY for research. MeSH indexes TERMS for
literature retrieval. They are not competitors; they carve the space
differently, and each carries strings the other lacks. MeSH's value
here is its ENTRY TERMS: the alternate names NLM curates so a search
finds a paper no matter which name the authors used.

Confirmed on the real FDA COA catalog: MeSH resolved two conditions
MONDO missed outright (Alcohol use disorder -> D000437; Opioid use
disorder -> D009293), each cross-referencing back to a MONDO class. A
small lift, but a real one, and it is exactly the multi-authority
behavior the architecture depends on.

Scope: DISEASE descriptors only -- tree numbers beginning "C"
(Diseases) or "F03" (Mental Disorders). Chemicals, techniques,
organisms, and the rest of MeSH are excluded; they are not disease
identity and would only add false-match surface.

Also confirmed: MeSH does NOT have "chronic heart failure" (it has
Heart Failure, with Congestive Heart Failure among fifteen entry
terms). Neither does MONDO. That string -- FDA's own -- exists in
neither research vocabulary, and is resolved instead by SNOMED, whose
job is clinical language. That is not a MeSH defect. It is the reason
more than one source is required.

Output: fda_data/mesh_disease_index.csv
  mesh_id, name, entry_terms, tree_numbers

The raw descriptor XML (~313 MB) is downloaded, parsed, and KEPT, so
anything the index does not carry remains reachable. Both are
gitignored; this script is the record.
"""

import csv
import os
import urllib.request
import xml.etree.ElementTree as ET

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
XML_FILE = os.path.join(DATA_DIR, "mesh_desc.xml")
INDEX_FILE = os.path.join(DATA_DIR, "mesh_disease_index.csv")

MESH_YEAR = "2026"
MESH_URL = (
    "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/"
    f"desc{MESH_YEAR}.xml"
)

OUTPUT_COLUMNS = [
    "mesh_id",
    "name",
    "entry_terms",
    "tree_numbers",
]


def _is_disease(tree_numbers: list[str]) -> bool:
    """C = Diseases; F03 = Mental Disorders. Everything else is out."""
    for number in tree_numbers:
        if number.startswith("C") or number.startswith("F03"):
            return True
    return False


def build_rows(xml_path: str) -> list[dict]:
    """Stream-parse the descriptor set; keep disease descriptors."""
    rows = []
    context = ET.iterparse(xml_path, events=("end",))
    for _, element in context:
        if element.tag != "DescriptorRecord":
            continue

        mesh_id = element.findtext("DescriptorUI")
        name = element.findtext("DescriptorName/String")
        trees = [
            node.text
            for node in element.findall("TreeNumberList/TreeNumber")
            if node.text
        ]

        if mesh_id and name and _is_disease(trees):
            terms = set()
            for term in element.findall(".//Term/String"):
                if term.text:
                    terms.add(term.text.strip())
            rows.append({
                "mesh_id": mesh_id,
                "name": name,
                "entry_terms": "|".join(sorted(terms)),
                "tree_numbers": "|".join(trees),
            })

        element.clear()
    return rows


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(XML_FILE):
        size = os.path.getsize(XML_FILE)
        print(f"Using existing {XML_FILE} ({size:,} bytes)")
        print("  delete it to force a fresh download")
    else:
        print(f"Downloading MeSH {MESH_YEAR} descriptors (~313 MB)...")
        urllib.request.urlretrieve(MESH_URL, XML_FILE)
        size = os.path.getsize(XML_FILE)
        print(f"  downloaded {size:,} bytes")

    print("Parsing (streamed; this takes a minute)...")
    rows = build_rows(XML_FILE)

    with open(INDEX_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    total_terms = sum(
        len(row["entry_terms"].split("|")) if row["entry_terms"] else 0
        for row in rows
    )

    print()
    print(f"Wrote {len(rows)} disease descriptors to {INDEX_FILE}")
    print(f"  total entry terms: {total_terms}")
    print(f"Raw XML kept at {XML_FILE}")


if __name__ == "__main__":
    main()
