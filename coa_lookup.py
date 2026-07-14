"""
coa_lookup.py
-------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Given a RESOLVED condition, what COAs does FDA have?

One job. It does not resolve identity -- condition_resolver did that
and sealed it. It does not walk a hierarchy. It does not judge whether
an instrument APPLIES to anyone's trial; that is a regulatory and
clinical judgment, and no tool here makes it.

It receives a CUI. It checks FDA's catalog. It returns what is there,
or it says plainly that there is nothing.

THE HANDOFF

Both sides speak the same identifier. The user's condition resolves to
a CUI. Every one of FDA's 54 catalog conditions has a CUI, produced by
the SAME resolver (fda_data/coa_resolution.csv). So the join is on a
settled identity, not on a string.

That is the whole point of resolving first. A string comparison would
ask "does the user's spelling match FDA's spelling," which is a
question about typing. A CUI comparison asks "is this the same
disease," which is the question that matters.

THE EMPTY RESULT IS THE PRODUCT

FDA's page cannot say "there is no COA for your disease."

It is a browser doing character matching on an HTML table. Type
"heart failure" and you get a hit -- because those words happen to sit
inside "Chronic Heart Failure." Type "congestive heart failure," which
is what most clinicians and every patient says, and you get NOTHING.
Type "HF," the abbreviation the field actually uses now, and you get
four hits -- because HF is a substring of CHF. Whether you find
anything depends on whether your letters appear inside theirs.

And a blank teaches the user nothing. It is indistinguishable from a
typo, a broken search, or a disease FDA never considered. A developer
searching breast cancer today gets a blank and walks away with no idea
that FDA has never qualified a COA for the most common cancer in
American women.

This tool can say it: WE RESOLVED YOUR CONDITION. WE CHECKED ALL 54.
THERE IS NOTHING. That is an answer. It is actionable. It is the first
thing anyone would need in order to ever fill the gap.

WHY A SYNONYM LIST CANNOT DO THIS

Two reasons, and the second is fatal.

First, scale: UMLS carries 539 distinct concepts containing "heart
failure." SNOMED alone has 159. ICD-10 has 36 codes. They are not
synonyms -- they are different diseases, crossed on acuity (acute /
chronic / acute-on-chronic), mechanism (systolic / diastolic /
combined), laterality, and etiology. A synonym list would flatten all
539 into one bucket. That is not compression; it is destruction. A
trial in acute decompensated HFrEF is not a trial in chronic HFpEF.

Second, and fatally: A SYNONYM LIST CAN ONLY CONTAIN WORDS FOR THINGS
THAT ARE IN THE CATALOG. To say "there is no COA for breast cancer,"
you would have to add breast cancer as a keyword pointing at NOTHING --
and then do that for every disease in medicine, so the page can tell
people what it does not have. Absence has no entry to hang a keyword
on. Resolution gets it for free.

CONTEXT OF USE COMES FROM THE DOCUMENT, NOT THE TABLE

The catalog's Context of Use column for all four heart failure COAs
reads: "Patients with CHF."

The KCCQ's actual qualification statement reads:
    Adults aged 18 years and older
    Diagnosis of stage C & D heart failure, NYHA Classes I-IV
    Heart failure patients with preserved or reduced ventricular
    function (HFpEF or HFrEF)

That is a staged, functionally classified population -- and the axes on
which it is defined are not even the ones the catalog string names. The
table is a LOSSY INDEX over documents that hold the real specification.

So this tool returns what the catalog says AND points at the documents
that govern. It does not summarize them, and it does not infer from
them. The document is the authority.

INPUTS
  fda_data/coa_resolution.csv       the 54 catalog conditions, resolved
  fda_data/coa_submissions.csv      instrument, concept, context, stage
  fda_data/qualified_coas.csv       the 7 that were ever qualified
  fda_data/coa_documents_index.csv  the 143 public documents
"""

import csv
import os
import sys

import condition_resolver as cr

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")

RESOLUTION_CSV = os.path.join(DATA_DIR, "coa_resolution.csv")
SUBMISSIONS_CSV = os.path.join(DATA_DIR, "coa_submissions.csv")
QUALIFIED_CSV = os.path.join(DATA_DIR, "qualified_coas.csv")
DOCUMENTS_CSV = os.path.join(DATA_DIR, "coa_documents_index.csv")

STATUS_FOUND = "COA_FOUND"
STATUS_NONE = "NO_COA"
STATUS_UNRESOLVED = "CONDITION_UNRESOLVED"

# Resolved, but by an authority that does not issue a CUI. These
# conditions are no less IDENTIFIED -- ClinicalTrials.gov confirmed
# them as registered trial conditions, and FDA guidance defines the
# other. They join on the normalized name.
#
# An earlier version joined on CUI alone, which silently abandoned
# exactly the seven conditions that needed the trial registry most.
# A user searching Community-Acquired Bacterial Pneumonia was told
# the condition could not be resolved -- when it HAD been, by a
# different authority. The consumer takes what the resolver
# produced. That is what a sealed handoff means.
RESOLVED_WITHOUT_CUI = (
    "RESOLVED_AS_TRIAL_POPULATION",
    "RESOLVED_BY_GUIDANCE",
)

QUALIFIED = "QUALIFIED"


def load_catalog() -> dict:
    """
    FDA's catalog, keyed by CUI.

    Every catalog condition was resolved by the SAME resolver the user's
    query goes through, so both sides carry the same identifier. Rows
    whose condition did not resolve to a CUI are kept in a separate
    bucket -- they are still real COAs, and pretending they do not exist
    would be its own kind of lie.
    """
    by_cui: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    unresolved: list[dict] = []
    entries: list[dict] = []

    with open(RESOLUTION_CSV, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            entry = {
                "condition": row["condition"],
                "cui": row["cui"],
                "label": row["label"],
                "status": row["status"],
                "n_sources": row["n_sources"],
                "coas": [],
            }
            entries.append(entry)

            if row["cui"]:
                by_cui.setdefault(row["cui"], []).append(entry)
            elif row["status"] in RESOLVED_WITHOUT_CUI:
                key = cr.normalize(row["condition"])
                by_name.setdefault(key, []).append(entry)
            else:
                unresolved.append(entry)

    # attach the COAs themselves
    for path, qualified in ((SUBMISSIONS_CSV, False),
                            (QUALIFIED_CSV, True)):
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                condition = (row.get("Disease/Condition") or "").strip()
                coa = {
                    "instrument": (
                        row.get("DDT COA Number and Instrument Name")
                        or "").strip(),
                    "concept": (row.get("Concept of Interest")
                                or "").strip(),
                    "context_of_use": (row.get("Context of Use")
                                       or "").strip(),
                    "coa_type": (row.get("COA Type") or "").strip(),
                    "stage": (QUALIFIED if qualified
                              else (row.get("Qualification Stage")
                                    or "").strip()),
                    "qualified": qualified,
                }
                for entry in entries:
                    if entry["condition"] == condition:
                        entry["coas"].append(coa)

    return {"by_cui": by_cui, "by_name": by_name,
            "unresolved": unresolved, "entries": entries}


def _documents_for(instrument: str, documents: list[dict]) -> list[dict]:
    """
    The public documents for a COA.

    The catalog is a LOSSY INDEX. The Context of Use column says
    "Patients with CHF." The KCCQ's qualification statement says stage
    C & D, NYHA I-IV, HFpEF or HFrEF. The document governs, and this
    tool points at it rather than summarizing it.
    """
    number = ""
    for token in instrument.replace("#", " ").split():
        digits = "".join(c for c in token if c.isdigit())
        if len(digits) >= 4:
            number = digits[-6:].zfill(6)
            break
    if not number:
        return []

    hits = []
    for document in documents:
        coa_number = (document.get("coa_number") or "").strip()
        if coa_number and coa_number.zfill(6) == number:
            hits.append({
                "label": document.get("document_label", ""),
                "url": document.get("document_url", ""),
                "filename": document.get("filename", ""),
            })
    return hits


def _catalog_size(catalog: dict) -> int:
    """
    How many DISTINCT conditions FDA's catalog holds.

    54 ROWS, 52 distinct conditions. The resolver found two duplicate
    pairs in FDA's own catalog:

        "Crohn's Disease (CD)"  and  "Crohn's disease (CD)"
            -- identical but for a capital D
        "Irritable Bowel Syndrome"  and  "Irritable Bowel Syndrome (IBS)"

    Both collapse onto one CUI, correctly. Not a defect in the join --
    a data-quality finding, and one that ONLY surfaces once conditions
    are resolved to CONCEPTS instead of matched as STRINGS. A keyword
    system would have shown a user two separate Crohn's entries and
    never known they were the same disease.
    """
    return (len(catalog["by_cui"])
            + len(catalog["by_name"])
            + len(catalog["unresolved"]))


def load_documents() -> list[dict]:
    if not os.path.exists(DOCUMENTS_CSV):
        return []
    with open(DOCUMENTS_CSV, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def lookup(resolved: dict, catalog: dict,
           documents: list[dict]) -> dict:
    """
    The COAs FDA has for this resolved condition -- or, honestly, none.

    Takes the SEALED object from condition_resolver. Does not re-derive
    identity, does not second-guess it, does not look at the string
    again.
    """
    entries = []
    if resolved.get("cui"):
        entries = catalog["by_cui"].get(resolved["cui"], [])
    elif resolved.get("status") in RESOLVED_WITHOUT_CUI:
        key = cr.normalize(resolved.get("query", ""))
        entries = catalog["by_name"].get(key, [])

    identified = bool(resolved.get("cui")) or (
        resolved.get("status") in RESOLVED_WITHOUT_CUI)

    if not identified:
        return {
            "query": resolved.get("query", ""),
            "status": STATUS_UNRESOLVED,
            "cui": "",
            "label": "",
            "coas": [],
            "catalog_size": _catalog_size(catalog),
            "note": (f'The condition did not resolve to a concept '
                     f'({resolved.get("status", "")}). No lookup is '
                     f'possible. This is not a statement that FDA has '
                     f'no COA -- it is a statement that we could not '
                     f'determine what disease this is.'),
        }

    coas = []
    for entry in entries:
        for coa in entry["coas"]:
            coa = dict(coa)
            coa["catalog_condition"] = entry["condition"]
            coa["documents"] = _documents_for(coa["instrument"],
                                              documents)
            coas.append(coa)

    catalog_size = _catalog_size(catalog)

    if not coas:
        return {
            "query": resolved["query"],
            "status": STATUS_NONE,
            "cui": resolved.get("cui", ""),
            "label": resolved.get("label", ""),
            "coas": [],
            "catalog_size": catalog_size,
            "note": (f'Resolved to '
                     f'{resolved.get("cui") or resolved["status"]} '
                     f'({resolved.get("label", "")}). Checked all '
                     f'{catalog_size} distinct conditions in the FDA COA '
                     f'catalog. FDA has no qualified or in-process '
                     f'clinical outcome assessment for this '
                     f'condition.'),
        }

    return {
        "query": resolved["query"],
        "status": STATUS_FOUND,
        "cui": resolved.get("cui", ""),
        "label": resolved.get("label", ""),
        "coas": coas,
        "catalog_size": catalog_size,
        "note": "",
    }


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python3 coa_lookup.py "disease name"')
        return

    catalog = load_catalog()
    documents = load_documents()
    context = cr.load_sources()

    for name in sys.argv[1:]:
        resolved = cr.resolve(name, context)
        result = lookup(resolved, catalog, documents)

        print()
        print(f'QUERY: "{result["query"]}"')
        print(f'  resolved : {result["cui"]}  {result["label"]}')
        print(f'  status   : {result["status"]}')
        print()

        if result["status"] != STATUS_FOUND:
            print(f'  {result["note"]}')
            print()
            continue

        print(f'  FDA has {len(result["coas"])} COA(s) for this '
              f'condition:')
        print()
        for coa in result["coas"]:
            mark = "  [QUALIFIED]" if coa["qualified"] else ""
            print(f'    {coa["instrument"]}{mark}')
            print(f'        filed under : {coa["catalog_condition"]}')
            print(f'        concept     : {coa["concept"]}')
            print(f'        context     : {coa["context_of_use"]}')
            print(f'        type        : {coa["coa_type"]}')
            print(f'        stage       : {coa["stage"]}')
            if coa["documents"]:
                print(f'        documents   : '
                      f'{len(coa["documents"])} public')
                for document in coa["documents"][:4]:
                    print(f'            {document["label"]}')
                print('        NOTE: the catalog context-of-use '
                      'column is a lossy summary.')
                print('        The qualification statement governs. '
                      'Read the document.')
            print()


if __name__ == "__main__":
    main()
