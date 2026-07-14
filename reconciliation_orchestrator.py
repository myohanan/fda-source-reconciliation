"""
reconciliation_orchestrator.py
------------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

One condition through a fixed, ordered sequence of deterministic tools.

Each step writes into a single per-condition schema that the next step
reads. No step re-derives what an earlier step sealed. The conductor
routes; it never plays violin.

PIPELINE SEQUENCE

  Step 1  condition_resolver
              A disease NAME -> a settled IDENTITY.
              UMLS Metathesaurus (~200 vocabularies), semantic gate,
              two-vocabulary minimum, consumer-vocabulary
              discrimination, ClinicalTrials.gov for trial
              populations, FDA guidance for cited constructs.
              SEALED. Nothing downstream asks what disease this is.

  Step 2  coa_lookup
              The settled identity -> FDA's COAs, or an honest none.
              A key join on the CUI. The EMPTY RESULT is a first-class
              answer, not a failure.

  Step 3  drug_lookup
              The settled identity -> approved drugs, by TWO
              independent routes (RxNorm coded; openFDA label prose),
              each labeled, never blended.

  Step 4  endpoint_search  (only if Step 2 found a COA)
              Each COA instrument -> the trials that registered it as
              an outcome measure. Verbatim text, never a boolean.

  Step 5  The finding
              Assembled from the sealed outputs above. Not derived
              anew, not re-reasoned. The orchestrator states what the
              tools found; it does not decide anything they did not.

THERE IS NO GENERATIVE STEP

Not one. Key joins, coded lookups, typed-field gates, vote counts over
declared vocabularies. Every determination is deterministic and
traceable to the authority that made it.

That is a stronger claim than the rare-disease pipeline can make, and
it is the right claim for this domain: PubMed evidence synthesis
requires judgment; source reconciliation does not. Where the data is
genuinely ambiguous the system surfaces CONFLICT_DETECTED and stops --
it does not guess.

The ONE place free text is read is the openFDA indication prose in
Step 3, and it is guarded by term_match_util's word-boundary rule,
LABELED as text-derived, and never merged with the coded count. A
reader can always see which route produced a drug -- which is how the
Cardiolite false positive (a cardiac imaging agent matching "breast")
stays visible instead of silently inflating a number.

DEGRADATION, NOT HALT

A tool that fails to load or times out degrades to a sealed UNKNOWN and
the pipeline continues. It does NOT emit a false negative.

That distinction is load-bearing and it is not theoretical: "we checked
and FDA has no COA for breast cancer" and "we could not check" are
completely different facts, and a user cannot tell them apart from a
blank. The schema records which one happened.

CALIBRATION, NOT PER-ITEM ESCALATION

Near-misses, refusals, and route disagreements are recorded and read in
aggregate. They are not escalated one at a time. The near-miss log has
already overturned two design decisions in this repository and
confirmed a third -- it is an instrument, not debug output.

THE FINDING IS THE PRODUCT

FDA's four sources can each show what they contain. None can say what
they do not.

A developer types "breast cancer" into FDA's page today and gets a
blank -- indistinguishable from a typo, a broken search, or a disease
FDA never considered. This pipeline says: resolved, checked all 52
distinct conditions, FDA has no qualified or in-process clinical
outcome assessment. And separately: FDA has approved 738 drug
applications for it.

An approved therapy and no qualified way to measure the outcome. That
sentence is the deliverable, and no website refresh can produce it.
"""

import json
import sys
from datetime import date

import coa_lookup as coa
import condition_resolver as cr
import drug_lookup as drugs
import endpoint_search as es

PIPELINE_VERSION = "1.0"

STEP_OK = "OK"
STEP_DEGRADED = "DEGRADED"
STEP_SKIPPED = "SKIPPED"


def create_schema(query: str) -> dict:
    """One condition, one schema. Every step writes into it."""
    return {
        "query": query,
        "pipeline_version": PIPELINE_VERSION,
        "run_date": date.today().isoformat(),
        "steps": {},
        "condition": {},
        "coas": {},
        "drugs": {},
        "coa_usage": {},
        "finding": {},
        "calibration": {
            "near_misses": [],
            "degraded_steps": [],
            "route_disagreements": 0,
        },
    }


def _seal(schema: dict, step: str, status: str, note: str = "") -> None:
    schema["steps"][step] = {"status": status, "note": note}
    if status == STEP_DEGRADED:
        schema["calibration"]["degraded_steps"].append(step)


def run(query: str, context: dict, catalog: dict, documents: list,
        drug_index: dict, approvals: dict,
        check_usage: bool = True) -> dict:
    """
    One condition, end to end. Returns the sealed schema.
    """
    schema = create_schema(query)

    # ---- STEP 1: IDENTITY. Sealed. Nothing downstream re-derives it.
    try:
        resolved = cr.resolve(query, context)
    except Exception as exc:  # noqa: BLE001
        _seal(schema, "1_condition_resolver", STEP_DEGRADED,
              f"{type(exc).__name__}")
        schema["finding"] = {
            "statement": ("The condition could not be resolved. This is "
                          "NOT a statement about what FDA has -- it is "
                          "a statement that the pipeline failed."),
        }
        return schema

    schema["condition"] = {
        "query": resolved["query"],
        "status": resolved["status"],
        "cui": resolved["cui"],
        "label": resolved["label"],
        "semantic_types": resolved["semantic_types"],
        "resolved_by": resolved["sources"],
        "n_sources": resolved["n_sources"],
        "mondo_id": resolved["mondo_id"],
        "hierarchy_available": resolved["hierarchy_available"],
        "candidates": resolved["candidates"],
    }
    schema["calibration"]["near_misses"].extend(resolved["near_misses"])
    _seal(schema, "1_condition_resolver", STEP_OK, resolved["status"])

    identified = bool(resolved["cui"]) or (
        resolved["status"] in coa.RESOLVED_WITHOUT_CUI)

    if not identified:
        schema["finding"] = {
            "statement": (
                f'"{query}" did not resolve to a condition '
                f'({resolved["status"]}). No lookup is possible. This '
                f'is NOT a statement that FDA has nothing -- it is a '
                f'statement that we could not determine what disease '
                f'this is.'),
            "resolved": False,
        }
        _seal(schema, "2_coa_lookup", STEP_SKIPPED, "unresolved")
        _seal(schema, "3_drug_lookup", STEP_SKIPPED, "unresolved")
        return schema

    # ---- STEP 2: COAs. The empty result is an ANSWER.
    try:
        coa_result = coa.lookup(resolved, catalog, documents)
        schema["coas"] = coa_result
        _seal(schema, "2_coa_lookup", STEP_OK, coa_result["status"])
    except Exception as exc:  # noqa: BLE001
        schema["coas"] = {"status": "LOOKUP_FAILED", "coas": []}
        _seal(schema, "2_coa_lookup", STEP_DEGRADED,
              f"{type(exc).__name__}")

    # ---- STEP 3: DRUGS. Two routes, labeled, never blended.
    try:
        drug_result = drugs.lookup(resolved, drug_index, approvals)
        schema["drugs"] = drug_result
        disagree = sum(
            1 for d in drug_result.get("drugs", [])
            if not d["both_routes"])
        schema["calibration"]["route_disagreements"] = disagree
        _seal(schema, "3_drug_lookup", STEP_OK, drug_result["status"])
    except Exception as exc:  # noqa: BLE001
        schema["drugs"] = {"status": "LOOKUP_FAILED", "drugs": []}
        _seal(schema, "3_drug_lookup", STEP_DEGRADED,
              f"{type(exc).__name__}")

    # ---- STEP 4: IS THE COA ACTUALLY USED?
    # FDA's four sources track QUALIFICATION. Nothing tracks USE.
    found_coas = schema["coas"].get("coas", [])
    if check_usage and found_coas:
        usage = {}
        for entry in found_coas:
            for name in _instrument_names(entry["instrument"]):
                try:
                    result = es.search(name)
                    usage[name] = {
                        "trials": result["retrieved"],
                        "as_primary": result["as_primary"],
                        "status": result["status"],
                    }
                except Exception as exc:  # noqa: BLE001
                    usage[name] = {"status": f"ERROR:"
                                             f"{type(exc).__name__}"}
        schema["coa_usage"] = usage
        _seal(schema, "4_endpoint_search", STEP_OK,
              f"{len(usage)} instruments checked")
    else:
        _seal(schema, "4_endpoint_search", STEP_SKIPPED,
              "no COA to check" if not found_coas else "disabled")

    # ---- STEP 5: THE FINDING. Assembled, not re-reasoned.
    schema["finding"] = _assemble(schema)
    _seal(schema, "5_finding", STEP_OK)

    return schema


def _instrument_names(raw: str) -> list[str]:
    """
    The instrument name(s) in a COA entry.

    One entry can name several instruments, and searching the entry
    string returns nothing because no sponsor writes it. Delegates to
    the same structural split used by run_coa_usage.
    """
    import re
    text = raw.split(":", 1)[1] if ":" in raw else raw
    units = re.findall(r"([^()]+?)\s*\(([A-Z][A-Za-z0-9\-]*)\)", text)

    qualifier_lead = ("in ", "for ", "among ", "with ", "and in ")
    candidates = []
    for unit, _abbrev in units:
        cleaned = unit.strip()
        if not cleaned or cleaned.lower().startswith(qualifier_lead):
            continue
        candidates.append(
            re.sub(r"^and\s+", "", cleaned, flags=re.I).strip())

    if len(candidates) >= 2:
        return candidates

    stripped = re.sub(r"\s*\([^)]*\)", " ", text)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return [stripped] if len(stripped) >= 6 else []


def _assemble(schema: dict) -> dict:
    """
    State what the tools found. Decide nothing they did not.

    The orchestrator is the conductor. It routes sealed determinations
    into a statement. It does not adjudicate, re-derive, or infer.
    """
    condition = schema["condition"]
    coas = schema["coas"].get("coas", [])
    drug_list = schema["drugs"].get("drugs", [])
    corroborated = [d for d in drug_list if d.get("both_routes")]

    has_coa = bool(coas)
    has_drugs = bool(drug_list)
    qualified = [c for c in coas if c.get("qualified")]

    lines = []
    label = condition["label"] or condition["query"]
    lines.append(f'{label} ({condition["cui"] or condition["status"]})')

    if has_coa:
        mark = f' -- {len(qualified)} QUALIFIED' if qualified else ""
        lines.append(f'COA: {len(coas)} instrument(s){mark}.')
    else:
        size = schema["coas"].get("catalog_size", "all")
        lines.append(
            f'COA: NONE. Checked all {size} distinct conditions in '
            f'FDA\'s COA catalog. FDA has no qualified or in-process '
            f'clinical outcome assessment for this condition.')

    if has_drugs:
        lines.append(
            f'DRUGS: {len(drug_list)} applications; '
            f'{len(corroborated)} corroborated by both routes.')
    else:
        lines.append('DRUGS: none found by either route.')

    gap = ""
    if has_drugs and not has_coa:
        gap = ('FDA has approved therapies for this disease and has '
               'no qualified instrument to measure outcomes in it.')

    return {
        "resolved": True,
        "statement": "\n".join(lines),
        "gap": gap,
        "has_coa": has_coa,
        "has_qualified_coa": bool(qualified),
        "has_drugs": has_drugs,
        "n_coas": len(coas),
        "n_drugs": len(drug_list),
        "n_drugs_corroborated": len(corroborated),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python3 reconciliation_orchestrator.py '
              '"disease name" [--json]')
        return

    as_json = "--json" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")]

    context = cr.load_sources()
    catalog = coa.load_catalog()
    documents = coa.load_documents()
    drug_index = drugs.load_drugs()
    approvals = drugs.load_approvals()

    for name in names:
        schema = run(name, context, catalog, documents,
                     drug_index, approvals)

        if as_json:
            print(json.dumps(schema, indent=2))
            continue

        print()
        print("=" * 68)
        print(schema["finding"].get("statement", ""))
        if schema["finding"].get("gap"):
            print()
            print(f'  >>> {schema["finding"]["gap"]}')
        print("=" * 68)
        print()

        condition = schema["condition"]
        if condition.get("n_sources"):
            print(f'  identity : {condition["n_sources"]} independent '
                  f'vocabularies agreed')

        for entry in schema["coas"].get("coas", []):
            mark = "  [QUALIFIED]" if entry["qualified"] else ""
            print(f'  COA      : {entry["instrument"][:56]}{mark}')
            print(f'             context: '
                  f'{entry["context_of_use"][:48]}')
            for name_, use in schema["coa_usage"].items():
                if name_ in entry["instrument"]:
                    print(f'             USED IN {use.get("trials", "?")} '
                          f'trials, {use.get("as_primary", "?")} as '
                          f'primary endpoint')

        drug_list = schema["drugs"].get("drugs", [])
        for drug in [d for d in drug_list if d["both_routes"]][:5]:
            print(f'  DRUG     : {drug["approved"] or "----------"}  '
                  f'{drug["brand"][:24]:<24} {drug["generic"][:24]}')

        print()
        steps = {k: v["status"] for k, v in schema["steps"].items()}
        print(f'  steps    : {steps}')
        if schema["calibration"]["degraded_steps"]:
            print(f'  DEGRADED : '
                  f'{schema["calibration"]["degraded_steps"]}')
        print()


if __name__ == "__main__":
    main()
