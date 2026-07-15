"""
build_snomed_index.py
---------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Builds the SNOMED CT US Edition hierarchy index -- the clinical-language
resolver's parent/child map, read from disk instead of fetched live.

WHY THIS EXISTS

hierarchy_matcher walks a concept's neighborhood -- parents, children,
siblings -- to answer "nothing for your condition, but here is what is
nearby." That walk was making live UMLS calls, one per neighbor, each
with a rate-limit pause: a no-COA query spent ~110 seconds resolving
neighbors over the network. The relations do not change between runs.

SNOMED is the source that walk uses, and it is the one source NOT
already on disk (MeSH, ICD-10, and MONDO indexes were built; SNOMED was
not). So this reads the same is-a hierarchy from the release files and
writes a local index. The neighbor walk then reads disk, not the API.

This is the same pattern as build_mesh_index.py: parse the raw release,
write a compact index, keep the raw zip, gitignore both. The script is
the record.

WHAT IS KEPT

Only ACTIVE is-a relationships (typeId 116680003) -- the taxonomic
backbone. Every other relationship type (finding site, causative agent,
and the rest) is excluded; they are not is-a and would not belong in a
parent/child walk. Inactive rows are excluded: a retired edge is not a
current relation.

Names come from the Description file: the Fully Specified Name is the
canonical label, and active synonyms are kept alongside it so a lookup
by any active term still lands.

Output: fda_data/snomed_index.json
    {
      "concept_id": {
        "name": "Fully Specified Name",
        "parents": ["parent_id", ...],
        "children": ["child_id", ...]
      },
      ...
    }

Siblings are NOT stored -- they are derivable (a concept's siblings are
its parents' other children) and storing them would triple the file for
no new information. hierarchy_matcher derives them, exactly as it does
from the live API today.
"""

import csv
import json
import os
import sys
import zipfile

# SNOMED description terms can exceed Python's default CSV field limit
# (131072 chars) -- SNOMED raised the max description length in 2026.
# Lift the limit to the platform maximum so the reader does not abort.
csv.field_size_limit(sys.maxsize)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
ZIP_FILE = os.path.join(DATA_DIR, "SnomedCT_USEdition_20260301.zip")
INDEX_FILE = os.path.join(DATA_DIR, "snomed_index.json")

# RF2 metadata concept IDs -- these are SNOMED's own, stable identifiers.
IS_A_TYPE_ID = "116680003"
FSN_TYPE_ID = "900000000000003001"

# Paths inside the release zip (confirmed by listing the archive).
_INNER = ("SnomedCT_ManagedServiceUS_PRODUCTION_US1000124_"
          "20260301T120000Z/Snapshot/Terminology/")
REL_PATH = _INNER + "sct2_Relationship_Snapshot_US1000124_20260301.txt"
DESC_PATH = (_INNER
             + "sct2_Description_Snapshot-en_US1000124_20260301.txt")


def _open_member(zf: zipfile.ZipFile, path: str):
    """A text handle onto one RF2 file inside the zip, UTF-8, tab-sep."""
    raw = zf.open(path, "r")
    return (line.decode("utf-8") for line in raw)


def parse_relationships(zf: zipfile.ZipFile) -> dict:
    """
    Active is-a edges only. Returns {concept: {"parents", "children"}}.

    RF2 relationship columns: id, effectiveTime, active, moduleId,
    sourceId, destinationId, relationshipGroup, typeId, ...
    A source is-a destination: the source is the CHILD, the destination
    is the PARENT.
    """
    nodes: dict[str, dict] = {}
    lines = _open_member(zf, REL_PATH)
    reader = csv.reader(lines, delimiter="\t")
    header = next(reader, None)
    if header is None:
        return nodes
    for row in reader:
        if len(row) < 8:
            continue
        active = row[2]
        source_id = row[4]
        destination_id = row[5]
        type_id = row[7]
        if active != "1" or type_id != IS_A_TYPE_ID:
            continue
        child = source_id
        parent = destination_id
        nodes.setdefault(child, {"parents": set(), "children": set()})
        nodes.setdefault(parent, {"parents": set(), "children": set()})
        nodes[child]["parents"].add(parent)
        nodes[parent]["children"].add(child)
    return nodes


def parse_names(zf: zipfile.ZipFile) -> dict:
    """
    Active descriptions. Returns {concept: fully_specified_name}, and
    falls back to any active term if no FSN is present.

    RF2 description columns: id, effectiveTime, active, moduleId,
    conceptId, languageCode, typeId, term, caseSignificanceId
    """
    fsn: dict[str, str] = {}
    any_term: dict[str, str] = {}
    lines = _open_member(zf, DESC_PATH)
    reader = csv.reader(lines, delimiter="\t")
    header = next(reader, None)
    if header is None:
        return fsn
    for row in reader:
        if len(row) < 8:
            continue
        active = row[2]
        concept_id = row[4]
        type_id = row[6]
        term = row[7]
        if active != "1":
            continue
        if type_id == FSN_TYPE_ID:
            fsn[concept_id] = term
        else:
            any_term.setdefault(concept_id, term)
    for concept_id, term in any_term.items():
        fsn.setdefault(concept_id, term)
    return fsn


def build_index(zip_path: str) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        nodes = parse_relationships(zf)
        names = parse_names(zf)

    index: dict[str, dict] = {}
    for concept_id, rel in nodes.items():
        index[concept_id] = {
            "name": names.get(concept_id, ""),
            "parents": sorted(rel["parents"]),
            "children": sorted(rel["children"]),
        }
    return index


def main() -> None:
    if not os.path.exists(ZIP_FILE):
        print(f"ERROR: {ZIP_FILE} not found.")
        print("Run download_snomed.py first.")
        sys.exit(1)

    print(f"Parsing {ZIP_FILE} (large; this takes a minute)...")
    index = build_index(ZIP_FILE)

    with open(INDEX_FILE, "w", encoding="utf-8") as handle:
        json.dump(index, handle)

    total_edges = sum(len(v["parents"]) for v in index.values())
    named = sum(1 for v in index.values() if v["name"])

    print()
    print(f"Wrote {len(index):,} concepts to {INDEX_FILE}")
    print(f"  is-a edges: {total_edges:,}")
    print(f"  concepts with a name: {named:,}")
    print(f"Raw release kept at {ZIP_FILE}")


if __name__ == "__main__":
    main()
