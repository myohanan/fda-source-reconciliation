"""
build_defining_attributes.py
----------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Records, for every SNOMED concept, whether it is DEFINED BY CLINICAL
ATTRIBUTES or is only a GROUPER.

WHY THIS EXISTS

A SIBLING relation is inferred THROUGH a shared parent. The relation is
only as meaningful as that parent. Congestive and chronic heart failure
share "Heart failure" -- a real disease, defined in SNOMED by finding
site, associated morphology, and more. Gaucher disease and cystic
fibrosis share "Autosomal recessive hereditary disorder" -- a grouper,
defined by NOTHING except an inheritance pattern. The first sibling is
navigation; the second is noise dressed as a relation.

SNOMED itself publishes the difference. A concept's DEFINING
relationships (finding site, associated morphology, pathological
process -- everything that is not an IS-A link) are what make it a
clinical entity. A pure grouper has none: "Navigational" and
inheritance-pattern groupers exist precisely to collect concepts
without stating defining attributes, because none can be stated.

Measured in the release:
    Heart failure (84114007)                     3 defining attributes
    Malignant neoplasm of lung (363358000)       2 defining attributes
    Autosomal recessive hereditary disorder      0 defining attributes
        (85995004)

So the rule the sibling gate applies: a shared parent with ZERO
defining attributes is a grouper, and a sibling inferred only through a
grouper is not surfaced. A shared parent WITH defining attributes is a
real disease family, and the sibling stands. This is not a threshold on
a count -- it is the published presence-or-absence of a concept model,
the same kind of typed-field gate the resolver uses for identity.

Output: fda_data/snomed_defined.json
    {code: true}   for every concept that has >= 1 defining attribute
Absence from the map means zero defining attributes (a grouper), so the
file stays small: only defined concepts are listed.
"""

import glob
import json
import os
import sys
import zipfile

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
OUTPUT_FILE = os.path.join(DATA_DIR, "snomed_defined.json")

# SNOMED RF2 Relationship file columns:
# id effectiveTime active moduleId sourceId destinationId
# relationshipGroup typeId characteristicTypeId modifierId
C_ACTIVE, C_SOURCE, C_TYPE = 2, 4, 7
IS_A = "116680003"   # every non-IS-A active relation is a defining attr


def _find_relationship_file(zf: zipfile.ZipFile) -> str:
    for name in zf.namelist():
        if ("sct2_Relationship_Snapshot" in name
                and "StatedRelationship" not in name
                and "Concrete" not in name):
            return name
    return ""


def build(zip_path: str) -> dict:
    """code -> True for every concept with >= 1 defining attribute."""
    defined: dict[str, bool] = {}
    with zipfile.ZipFile(zip_path) as zf:
        rel_path = _find_relationship_file(zf)
        if not rel_path:
            raise RuntimeError("no Relationship_Snapshot file in zip")
        with zf.open(rel_path) as handle:
            next(handle)  # header
            for line in handle:
                f = line.decode("utf-8").rstrip("\n").split("\t")
                if len(f) <= C_TYPE:
                    continue
                if f[C_ACTIVE] != "1":
                    continue
                if f[C_TYPE] == IS_A:
                    continue
                # A non-IS-A active relationship IS a defining attribute.
                defined[f[C_SOURCE]] = True
    return defined


def main() -> None:
    zips = glob.glob(os.path.join(DATA_DIR, "SnomedCT_USEdition_*.zip"))
    if not zips:
        print("ERROR: no SnomedCT_USEdition_*.zip in fda_data/.")
        sys.exit(1)
    zip_path = zips[0]
    print(f"Reading defining attributes from {os.path.basename(zip_path)}")
    defined = build(zip_path)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(defined, handle)
    print(f"Wrote {OUTPUT_FILE}")
    print(f"  {len(defined):,} concepts have >= 1 defining attribute")
    # spot check the three known cases
    for code, label in (("84114007", "Heart failure"),
                        ("363358000", "Malignant neoplasm of lung"),
                        ("85995004", "Autosomal recessive disorder")):
        mark = "DEFINED" if defined.get(code) else "GROUPER (0 attrs)"
        print(f"    {label}: {mark}")


if __name__ == "__main__":
    main()