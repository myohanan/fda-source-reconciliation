"""
build_mondo_index.py
--------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Builds the controlled-vocabulary source for condition RESOLUTION.

This is deliberately NOT a mapping table. A flat name -> id lookup is
the artifact that fails: it works on clean cases and then accumulates
exception rules for everything else. The architecture here is
resolution -- the vocabulary is a SOURCE the resolver reasons against,
producing a canonical object with confidence and conflict states, not a
dictionary it forces a match from.

What the index carries, and why each part is load-bearing:

  labels + exact/related synonyms
      The names a source might use. Exact and related are kept SEPARATE
      because they carry different confidence: an exact synonym is an
      identity claim; a related one is not.

  parents (the is_a hierarchy)
      MONDO is a POLYHIERARCHY: 10,657 of 32,095 classes have more than
      one parent. A one-to-one table structurally cannot represent that,
      which is exactly why mapping spawns exception rules.
      The hierarchy is also REQUIRED for this domain, not optional.
      Drugs@FDA indications and COA conditions routinely differ by
      subsumption rather than by name. Verified on real data:
        non-small cell lung carcinoma (MONDO:0005233)
          -> lung carcinoma (MONDO:0005138)
            -> lung cancer (MONDO:0008903)
      So a drug indicated for NSCLC and a COA for "lung cancer" is a
      PARENT/CHILD FINDING -- not a false match, not a false miss, and
      not an exception rule.

  xrefs across 12 vocabularies
      UMLS, MeSH, Orphanet, OMIM, DOID, SNOMED (SCTID), NCIT, GARD,
      MedGen, ICD9/10. Any source's vocabulary can reach the same
      canonical object. The Orphanet and OMIM xrefs mean this single
      vocabulary anchors BOTH this project and the rare-disease
      endpoint library.

  definitions
      When two sources disagree, the definition is what adjudicates.

KNOWN COVERAGE PROFILE (stated, not hidden): MONDO's gaps are the
NEWER and RARER diseases. In the rare-disease domain that gap is where
the pain lives. In THIS domain the conditions are common diseases with
mature coverage, so the gap is largely absent -- but MONDO changes over
time, so this index is a SNAPSHOT and should be rebuilt periodically.
Rebuilding is what this script is for.

Tested against the real COA condition strings: 12/14 resolved cleanly
after stripping the parenthetical abbreviation FDA embeds in its own
strings ("Chronic Kidney Disease (CKD)"). The two that did not are
instructive rather than defective -- "Chronic Heart Failure" is a
genuine synonym gap (MONDO has "heart failure" and "congestive heart
failure"), and "Sarcopenia" is arguably a phenotype rather than a
disease. Both are CONFLICT_DETECTED / HUMAN_REVIEW_REQUIRED cases. That
is the correct behavior.

Outputs (both gitignored):
  fda_data/mondo.json                  the full ontology, KEPT (~107 MB)
  fda_data/mondo_resolution_index.csv  the index (~10 MB)

The raw ontology is kept, not discarded, because the index is a
convenience over it -- anything the index does not carry (logical
definition axioms, further edge predicates) is still reachable.
"""

import csv
import json
import os
import urllib.request
from collections import defaultdict

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
ONTOLOGY_FILE = os.path.join(DATA_DIR, "mondo.json")
INDEX_FILE = os.path.join(DATA_DIR, "mondo_resolution_index.csv")

MONDO_URL = "http://purl.obolibrary.org/obo/mondo.json"

XREF_VOCABS = [
    "UMLS", "MESH", "Orphanet", "OMIM", "DOID", "SCTID",
    "NCIT", "GARD", "MEDGEN", "ICD9", "ICD10", "ICD10CM",
]

BASE_COLUMNS = [
    "mondo_id",
    "label",
    "exact_synonyms",
    "related_synonyms",
    "parents",
    "n_parents",
    "definition",
]


def _short_id(iri: str) -> str:
    """MONDO IRI -> compact CURIE (MONDO:0005233)."""
    return iri.split("/")[-1].replace("_", ":")


def build_parent_map(edges: list[dict]) -> dict[str, list[str]]:
    """MONDO -> MONDO is_a edges only. Polyhierarchy preserved."""
    parents = defaultdict(list)
    for edge in edges:
        if edge.get("pred") != "is_a":
            continue
        subject = edge.get("sub", "")
        obj = edge.get("obj", "")
        if "MONDO_" in subject and "MONDO_" in obj:
            parents[_short_id(subject)].append(_short_id(obj))
    return dict(parents)


def build_rows(graph: dict) -> list[dict]:
    """One row per live MONDO disease class."""
    parents = build_parent_map(graph.get("edges", []))
    rows = []

    for node in graph.get("nodes", []):
        node_id = node.get("id", "")
        if "MONDO_" not in node_id or node.get("type") != "CLASS":
            continue
        label = node.get("lbl")
        if not label:
            continue
        meta = node.get("meta", {})
        if meta.get("deprecated"):
            continue

        mondo_id = _short_id(node_id)

        exact = []
        related = []
        for synonym in meta.get("synonyms", []):
            value = synonym.get("val")
            if not value:
                continue
            if synonym.get("pred") == "hasExactSynonym":
                exact.append(value)
            else:
                related.append(value)

        xrefs = defaultdict(list)
        for xref in meta.get("xrefs", []):
            value = xref.get("val", "")
            if ":" not in value:
                continue
            prefix, rest = value.split(":", 1)
            if prefix in XREF_VOCABS:
                xrefs[prefix].append(rest)

        definition = (meta.get("definition") or {}).get("val", "")
        my_parents = parents.get(mondo_id, [])

        row = {
            "mondo_id": mondo_id,
            "label": label,
            "exact_synonyms": "|".join(exact),
            "related_synonyms": "|".join(related),
            "parents": "|".join(my_parents),
            "n_parents": len(my_parents),
            "definition": definition.replace("\n", " ")[:500],
        }
        for vocab in XREF_VOCABS:
            row[f"xref_{vocab.lower()}"] = "|".join(xrefs.get(vocab, []))
        rows.append(row)

    return rows


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(ONTOLOGY_FILE):
        size = os.path.getsize(ONTOLOGY_FILE)
        print(f"Using existing {ONTOLOGY_FILE} ({size:,} bytes)")
        print("  delete it to force a fresh download")
    else:
        print("Downloading MONDO (~107 MB)...")
        urllib.request.urlretrieve(MONDO_URL, ONTOLOGY_FILE)
        size = os.path.getsize(ONTOLOGY_FILE)
        print(f"  downloaded {size:,} bytes")

    print("Parsing...")
    with open(ONTOLOGY_FILE, encoding="utf-8") as handle:
        ontology = json.load(handle)

    rows = build_rows(ontology["graphs"][0])

    columns = BASE_COLUMNS + [
        f"xref_{vocab.lower()}" for vocab in XREF_VOCABS]
    with open(INDEX_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    multi = sum(1 for row in rows if row["n_parents"] > 1)
    defined = sum(1 for row in rows if row["definition"])

    print()
    print(f"Wrote {len(rows)} disease classes to {INDEX_FILE}")
    print(f"  multi-parent (polyhierarchy): {multi}")
    print(f"  with a definition:            {defined}")
    for vocab in XREF_VOCABS:
        key = f"xref_{vocab.lower()}"
        count = sum(1 for row in rows if row[key])
        if count:
            print(f"  with {vocab:<9} xref: {count}")
    print()
    print(f"Full ontology kept at {ONTOLOGY_FILE}")


if __name__ == "__main__":
    main()
