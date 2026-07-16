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

  neighbor_lookup       (only if Step 2 found NOTHING)
              The settled identity -> which catalog conditions are
              structurally related, and how. Six-source convergence
              via hierarchy_matcher, CUI-to-CUI, never re-resolving a
              name. Relations only.

  neighbor_coa_lookup   (only if neighbor_lookup found neighbors)
              The sealed neighbor list -> each neighbor's COAs,
              attached verbatim from the catalog.

              An empty COA result is honest and nearly useless on its
              own. FDA's catalog holds 54 conditions and medicine holds
              thousands, so almost every real query lands on an empty
              cell. A developer typing "congestive heart failure" gets
              NO COA -- while the KCCQ, qualified and used in 1,029
              trials with 117 primary endpoints, sits one SIBLING away
              under the same parent.

              NAVIGATION, NOT RECOMMENDATION. Surfacing a neighbor is
              not authorizing its use. Whether the KCCQ applies to an
              acute decompensated population is a REGULATORY question --
              its qualified context of use is "stage C & D heart
              failure, NYHA Classes I-IV, HFpEF or HFrEF," and that is
              FDA's determination, not this pipeline's.

              The RELATION LABEL is what keeps it navigation.

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
import trial_instruments as ti
import neighbor_lookup as nl
import neighbor_coa_lookup as ncl

PIPELINE_VERSION = "1.0"

STEP_OK = "OK"
STEP_DEGRADED = "DEGRADED"
STEP_SKIPPED = "SKIPPED"

_VERBOSE = False

_T0 = [None]


def _progress(text):
    """
    Say what the pipeline is doing, while it does it.

    Ninety seconds of silence reads as "it is broken." Ninety seconds
    with visible progress reads as "it is working." The machine is idle
    almost the whole time -- 1.7 seconds of CPU across a 90-second run,
    2% utilization -- because every step waits on a vocabulary service
    over the network. That is not a defect to hide; it is a fact to
    show.
    """
    if _VERBOSE:
        import time as _t
        now = _t.time()
        if _T0[0] is None:
            _T0[0] = now
        print("  ... %s  (+%.1fs)" % (text, now - _T0[0]), flush=True)


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
        "neighbors": [],
        "finding": {},
        "calibration": {
            "near_misses": [],
            "degraded_steps": [],
            "degraded_sources": [],
            "route_disagreements": 0,
        },
    }


def _seal(schema: dict, step: str, status: str, note: str = "") -> None:
    schema["steps"][step] = {"status": status, "note": note}
    if status == STEP_DEGRADED:
        schema["calibration"]["degraded_steps"].append(step)


def run(query: str, context: dict, catalog: dict, documents: list,
        drug_index: dict, approvals: dict,
        check_usage: bool = True,
        check_instruments: bool = True) -> dict:
    """
    One condition, end to end. Returns the sealed schema.
    """
    _progress('resolving "%s" against ~200 vocabularies' % query)
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

    # A LOOKUP FAILURE IS NOT A FINDING.
    #
    # If the vocabulary service could not be reached, the pipeline knows
    # NOTHING about this disease -- and it must say so in those terms.
    # It must not say "we could not determine what disease this is,"
    # which implies we looked. We did not look. The instrument was
    # broken.
    #
    # This distinction is not academic. An earlier version swallowed a
    # transient UMLS failure, returned empty semantic types, and the gate
    # read that as a rejection: the resolver reported that CONGESTIVE
    # HEART FAILURE IS NOT A CONDITION. A network hiccup produced a
    # statement about a disease, and nothing in the output looked broken.
    if resolved["status"] == cr.STATUS_LOOKUP_FAILED:
        schema["finding"] = {
            "statement": (
                f'PIPELINE FAILURE. The vocabulary service could not be '
                f'reached, so "{query}" was never looked up. This is a '
                f'statement about the SYSTEM, not about the disease and '
                f'not about FDA. Nothing below should be read as a '
                f'finding. Retry.'),
            "resolved": False,
            "system_failure": True,
        }
        _seal(schema, "1_condition_resolver", STEP_DEGRADED,
              "UMLS unreachable")
        _seal(schema, "2_coa_lookup", STEP_SKIPPED, "lookup failed")
        _seal(schema, "neighbor_lookup", STEP_SKIPPED, "lookup failed")
        _seal(schema, "neighbor_coa_lookup", STEP_SKIPPED,
              "lookup failed")
        _seal(schema, "3_drug_lookup", STEP_SKIPPED, "lookup failed")
        return schema

    identified = bool(resolved["cui"]) or (
        resolved["status"] in coa.RESOLVED_WITHOUT_CUI)

    if not identified:
        schema["finding"] = {
            "statement": (
                f'"{query}" did not resolve to a condition '
                f'({resolved["status"]}). We checked ~200 vocabularies, '
                f'the trial registry, and the cited guidance table. This '
                f'is NOT a statement that FDA has nothing -- it is a '
                f'statement that this string does not name a condition '
                f'any authority recognizes.'),
            "resolved": False,
        }
        _seal(schema, "2_coa_lookup", STEP_SKIPPED, "unresolved")
        _seal(schema, "neighbor_lookup", STEP_SKIPPED, "unresolved")
        _seal(schema, "neighbor_coa_lookup", STEP_SKIPPED, "unresolved")
        _seal(schema, "3_drug_lookup", STEP_SKIPPED, "unresolved")
        return schema

    _progress("checking FDA's COA catalog")
    # ---- STEP 2: COAs. The empty result is an ANSWER.
    try:
        coa_result = coa.lookup(resolved, catalog, documents)
        schema["coas"] = coa_result
        _seal(schema, "2_coa_lookup", STEP_OK, coa_result["status"])
    except Exception as exc:  # noqa: BLE001
        schema["coas"] = {"status": "LOOKUP_FAILED", "coas": []}
        _seal(schema, "2_coa_lookup", STEP_DEGRADED,
              f"{type(exc).__name__}")

    # ---- NEIGHBOR STEPS: NOTHING FOR YOUR CONDITION -- IS ANYTHING
    # NEARBY? Only when the catalog came back empty and the condition
    # has a CUI to relate from. Two single-function tools: neighbor_
    # lookup finds the related catalog conditions (six-source, CUI to
    # CUI, no re-resolution); neighbor_coa_lookup attaches their COAs.
    # The conductor routes their sealed outputs; it neither relates nor
    # attaches.
    if not schema["coas"].get("coas") and resolved.get("cui"):
        _run_neighbor_steps(schema, resolved, catalog)
    else:
        _seal(schema, "neighbor_lookup", STEP_SKIPPED,
              "a COA exists for this condition")
        _seal(schema, "neighbor_coa_lookup", STEP_SKIPPED,
              "a COA exists for this condition")

    _progress("checking approved drugs -- two independent routes")
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

    # ---- STEP 4b: WHAT DID THIS DISEASE'S APPROVAL TRIALS MEASURE?
    # For the approved drugs found in Step 3, pull the outcome measures
    # their trials used, flag which are FDA-qualified COAs, and group
    # the rest for readability. This is the "what is actually being
    # measured, and how little of it is a qualified COA" view.
    drug_generics = sorted({
        (d.get("generic") or "").strip()
        for d in schema["drugs"].get("drugs", [])
        if (d.get("generic") or "").strip()
    })
    if check_instruments and drug_generics:
        try:
            inst = ti.find_instruments(
                schema["condition"]["label"] or query,
                drug_generics, catalog)
            schema["trial_instruments"] = inst
            _seal(schema, "4b_trial_instruments", STEP_OK,
                  f"{inst.get('n_instruments', 0)} measures")
        except Exception as exc:  # noqa: BLE001
            schema["trial_instruments"] = {"status": "LOOKUP_FAILED",
                                           "instruments": []}
            _seal(schema, "4b_trial_instruments", STEP_DEGRADED,
                  f"{type(exc).__name__}")
    else:
        _seal(schema, "4b_trial_instruments", STEP_SKIPPED,
              "no approved drugs" if not drug_generics else "disabled")

    # ---- STEP 5: THE FINDING. Assembled, not re-reasoned.
    schema["finding"] = _assemble(schema)
    _seal(schema, "5_finding", STEP_OK)

    return schema


def _run_neighbor_steps(schema: dict, resolved: dict,
                        catalog: dict) -> None:
    """
    Route the two neighbor tools and seal each as its own step.

    neighbor_lookup finds the structurally related catalog conditions
    (six-source convergence, CUI to CUI). neighbor_coa_lookup attaches
    each neighbor's COAs from the catalog. The conductor calls each,
    records its sealed status, and stores the enriched neighbor list --
    it does not relate, resolve, or attach anything itself.

    Per-source failures from neighbor_lookup are recorded to
    calibration.degraded_sources: a source that ERRORED could not vote,
    which is a degradation, distinct from a source that answered "no
    relation." The step is not failed by a degraded source; it
    continues on the sources that answered.
    """
    _progress("nothing for this condition -- checking the neighborhood")
    try:
        neighbor_result = nl.find_neighbors(resolved, catalog)
    except Exception as exc:  # noqa: BLE001
        schema["neighbors"] = []
        _seal(schema, "neighbor_lookup", STEP_DEGRADED,
              f"{type(exc).__name__}")
        _seal(schema, "neighbor_coa_lookup", STEP_SKIPPED,
              "neighbor_lookup degraded")
        return

    degraded = neighbor_result.get("degraded_sources", []) or []
    if degraded:
        schema["calibration"]["degraded_sources"].extend(degraded)

    _seal(schema, "neighbor_lookup", STEP_OK,
          neighbor_result.get("status", ""))

    try:
        attached = ncl.attach_coas(neighbor_result, catalog)
        schema["neighbors"] = attached.get("neighbors", [])
        _seal(schema, "neighbor_coa_lookup", STEP_OK,
              attached.get("status", ""))
    except Exception as exc:  # noqa: BLE001
        schema["neighbors"] = []
        _seal(schema, "neighbor_coa_lookup", STEP_DEGRADED,
              f"{type(exc).__name__}")


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

    # Presentation trims to the neighbors that actually carry a COA;
    # neighbor_coa_lookup keeps COA-less neighbors in the data with
    # coas == [], but the NEARBY line is about where FDA HAS an
    # instrument. The complete list stays in schema["neighbors"].
    neighbors = schema.get("neighbors", [])
    with_coas = [n for n in neighbors if n.get("coas")]
    if not has_coa and with_coas:
        for n in with_coas[:3]:
            marks = [c for c in n["coas"] if c["qualified"]]
            mark = " (QUALIFIED)" if marks else ""
            lines.append(
                f'NEARBY: {n["condition"]} is a {n["relation"]} of your '
                f'condition, and FDA has {len(n["coas"])} COA(s) for '
                f'it{mark}. These are DIFFERENT concepts. Whether the '
                f'instrument applies to your population is a regulatory '
                f'judgment -- read its context of use.')

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


def _by_date(drug: dict) -> str:
    """Sort key: approval date, empty dates last."""
    d = drug.get("approved") or ""
    return d if d else "9999-99-99"


def _print_drug_line(drug: dict, show_indication: bool = False) -> None:
    date = drug.get("approved") or "----------"
    brand = (drug.get("brand") or "")[:24]
    generic = (drug.get("generic") or "")[:26]
    print(f'             {date}  {brand:<24}  {generic}')
    if show_indication:
        ind = (drug.get("indication") or "").strip()
        if ind:
            # The prose that produced a label-only match. Showing it is
            # how a false positive (a cardiac agent matching "breast")
            # stays visible instead of silently inflating a count.
            print(f'                 indication: {ind[:70]}')


def _print_drugs(drug_list: list) -> None:
    """
    The disease's approved drugs, grouped by which of the two routes
    found them. Corroborated (both routes) lead, chronological -- that
    ordering is the therapeutic history of the disease. Then the two
    single-route groups, because a route DISAGREEMENT is a finding, not
    noise: coded-only is MED-RT breadth beyond the approved label;
    label-only is the prose match, shown WITH its indication text so a
    string-match false positive is visible. NOTHING is capped -- how a
    long list is paged is a front-end concern; the backend reports it
    complete.
    """
    if not drug_list:
        print('  DRUGS    : none found by either route.')
        return

    both = sorted([d for d in drug_list if d.get("both_routes")],
                  key=_by_date)
    coded_only = sorted(
        [d for d in drug_list if not d.get("both_routes")
         and "rxnorm_may_treat" in (d.get("routes") or [])],
        key=_by_date)
    label_only = sorted(
        [d for d in drug_list if not d.get("both_routes")
         and "openfda_indication" in (d.get("routes") or [])
         and "rxnorm_may_treat" not in (d.get("routes") or [])],
        key=_by_date)

    print(f'  DRUGS    : {len(drug_list)} approved applications  '
          f'({len(both)} corroborated by both routes)')

    if both:
        print()
        print(f'    CORROBORATED -- both routes agree ({len(both)}), '
              f'oldest first:')
        for d in both:
            _print_drug_line(d)

    if coded_only:
        print()
        print(f'    CODED ROUTE ONLY ({len(coded_only)}) -- RxNorm '
              f'may_treat; the approved label does not name this '
              f'condition.')
        print('    may_treat is BROADER than an approved indication '
              '(off-label, class-level).')
        for d in coded_only:
            _print_drug_line(d)

    if label_only:
        print()
        print(f'    LABEL ROUTE ONLY ({len(label_only)}) -- matched the '
              f'openFDA indication text, not the coded route.')
        print('    Indication text shown so a string-match false '
              'positive is visible.')
        for d in label_only:
            _print_drug_line(d, show_indication=True)


def _print_trial_instruments(schema: dict) -> None:
    """
    What the approved drugs' trials actually measured -- shown the way
    trial_instruments shows it: every instrument by FULL NAME with its
    trial count, split into FDA-qualified COAs, CDISC-recognized
    instruments, and everything else. The scarcity of qualified COAs
    against the length of the rest is the point.
    """
    inst = schema.get("trial_instruments", {})
    measures = inst.get("instruments", [])
    if not measures:
        return
    qcoa = [m for m in measures if m.get("category") == "qualified_coa"]
    cdisc = [m for m in measures
             if m.get("category") == "cdisc_instrument"]
    other = [m for m in measures if m.get("category") == "other"]

    def _line(m):
        var = (f'  [{m["n_variants"]} phrasings]'
               if m.get("n_variants") else "")
        return (f'    {m["instrument"]}  '
                f'({m["trials"]} trials, {m["as_primary"]} primary)'
                f'{var}')

    print()
    print(f'  WHAT THE APPROVAL TRIALS MEASURED '
          f'({inst.get("n_trials", 0)} trials, '
          f'{len(measures)} distinct measures)')
    print()
    print(f'  FDA-QUALIFIED COAs used ({len(qcoa)}):')
    if not qcoa:
        print('    NONE -- no qualified COA appears in any of these '
              'trials.')
    for m in qcoa:
        print(_line(m))
    print()
    print(f'  RECOGNIZED INSTRUMENTS (in CDISC, not FDA-qualified) '
          f'({len(cdisc)}):')
    if not cdisc:
        print('    none.')
    for m in cdisc:
        print(_line(m))
    print()
    print(f'  OTHER measures -- not a recognized clinical instrument '
          f'(PK, safety, labs, biomarkers) ({len(other)}):')
    for m in other:
        print(_line(m))


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python3 reconciliation_orchestrator.py '
              '"disease name" [--json]')
        return

    global _VERBOSE
    as_json = "--json" in sys.argv
    _VERBOSE = not as_json
    names = [a for a in sys.argv[1:] if not a.startswith("--")]

    _progress("loading vocabularies and FDA source data")
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
        if schema["finding"].get("system_failure"):
            print("  *** PIPELINE FAILURE -- NOT A FINDING ***")
            print()
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

        # Display only the neighbors that carry a COA; the full list
        # (including COA-less neighbors) is in schema["neighbors"].
        display_neighbors = [
            n for n in schema.get("neighbors", []) if n.get("coas")]
        for n in display_neighbors[:3]:
            print()
            print(f'  NEARBY   : {n["condition"]}  '
                  f'[{n["relation"]} of your condition]')
            for c in n["coas"]:
                mark = "  [QUALIFIED]" if c["qualified"] else ""
                print(f'             {c["instrument"][:52]}{mark}')
                print(f'             context: '
                      f'{c["context_of_use"][:44]}')
            print('             NOTE: a different concept. Whether this')
            print('             instrument applies to your population is')
            print('             a REGULATORY judgment, not this tool\'s.')

        drug_list = schema["drugs"].get("drugs", [])
        _print_drugs(drug_list)

        _print_trial_instruments(schema)

        print()
        steps = {k: v["status"] for k, v in schema["steps"].items()}
        print(f'  steps    : {steps}')
        if schema["calibration"]["degraded_steps"]:
            print(f'  DEGRADED : '
                  f'{schema["calibration"]["degraded_steps"]}')
        if schema["calibration"]["degraded_sources"]:
            print(f'  DEGRADED SOURCES : '
                  f'{schema["calibration"]["degraded_sources"]}')
        print()


if __name__ == "__main__":
    main()