"""
coa_orchestrator.py
-------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

The COA-focused orchestration: everything FDA has for a disease that is
SHAPED BY THE COA, in one place.

This is the tight, thematic view -- distinct from
reconciliation_orchestrator, which is the expansive everything-view.
Here every section answers a COA question:

  1. condition_resolver   NAME -> sealed identity.
  2. coa_lookup           Does the disease ITSELF have a COA?
  3. neighbor_lookup +    If not, does a structurally related catalog
     neighbor_coa_lookup  condition (with the defining-attributes
                          sibling gate) have one?
  4. PER COA INSTRUMENT in the picture -- the disease's own, or a
     neighbor's -- two evidence pulls:
       endpoint_search    the trials that registered the instrument as
                          an outcome measure, primary vs secondary.
       coa_drug_link      the APPROVED drugs whose trials used the
                          instrument (co-occurrence, never an approval-
                          causation claim).

WHAT IT DOES AND DOES NOT SHOW

Every drug and every trial here traces to a COA instrument. When a
disease has a COA (its own or a neighbor's), that COA's trials and
approved drugs are shown, per instrument. When there is NO COA anywhere
-- not for the disease, not for any related catalog condition -- the
tool says so plainly and shows NOTHING on the drug or trial side,
because there is no COA to hang them on. A disease's approved drugs
that have no COA connection belong to the full reconciliation view, not
here.

That empty answer is not a failure. "FDA has no COA for this disease
and none for anything near it" is the exact fact a developer needs, and
it is the fact FDA's own page cannot state.

NO GENERATIVE STEP. Every determination is a key join, a coded lookup,
or a verbatim trial-registry read. The orchestrator routes sealed
outputs; it decides nothing the tools did not.
"""

import json
import os
import re
import sys
from datetime import date

import coa_lookup as coa
import condition_resolver as cr
import coa_drug_link as cdl
import endpoint_search as es
import neighbor_coa_lookup as ncl
import neighbor_lookup as nl

PIPELINE_VERSION = "1.0-coa"

_VERBOSE = False
_T0 = [None]


def _progress(text):
    if _VERBOSE:
        import time as _t
        now = _t.time()
        if _T0[0] is None:
            _T0[0] = now
        print("  ... %s  (+%.1fs)" % (text, now - _T0[0]), flush=True)


def _instrument_names(raw: str) -> list:
    """
    The instrument name(s) in a COA entry string.

    One catalog entry can name several instruments; searching the whole
    entry string returns nothing because no sponsor writes it that way.
    Same structural split the reconciliation orchestrator uses, so the
    two cannot drift: pull "Name (ABBREV)" units, drop qualifier-led
    fragments, and fall back to the de-parenthesized whole.
    """
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


def _evidence_for_instrument(instrument: str) -> dict:
    """
    The two per-instrument evidence pulls: trials (endpoint_search) and
    approved co-occurring drugs (coa_drug_link). Each degrades to its
    own error shape; neither failure stops the other.
    """
    trials = {"status": "NOT_RUN", "retrieved": 0,
              "as_primary": 0, "reported_total": None}
    try:
        result = es.search(instrument)
        trials = {
            "status": result.get("status", ""),
            "retrieved": result.get("retrieved", 0),
            "as_primary": result.get("as_primary", 0),
            "reported_total": result.get("reported_total"),
        }
    except Exception as exc:  # noqa: BLE001
        trials = {"status": f"ERROR:{type(exc).__name__}",
                  "retrieved": 0, "as_primary": 0,
                  "reported_total": None}

    drugs = {"status": "NOT_RUN", "drugs": [], "n_trials": 0}
    try:
        drugs = cdl.link(instrument, approved_only=True)
    except Exception as exc:  # noqa: BLE001
        drugs = {"status": f"ERROR:{type(exc).__name__}",
                 "drugs": [], "n_trials": 0}

    return {"trials": trials, "drugs": drugs}


def _coa_block(coa_entry: dict, source_label: str) -> dict:
    """
    One COA in the picture -> its full per-instrument evidence.

    source_label says where the COA came from: "this condition" when it
    is the disease's own, or "<neighbor> (<relation>)" when it belongs
    to a related catalog condition.
    """
    names = _instrument_names(coa_entry.get("instrument", ""))
    instruments = []
    for name in names:
        instruments.append({
            "instrument": name,
            "evidence": _evidence_for_instrument(name),
        })
    return {
        "coa_label": coa_entry.get("instrument", ""),
        "qualified": coa_entry.get("qualified", False),
        "context_of_use": coa_entry.get("context_of_use", ""),
        "stage": coa_entry.get("stage", ""),
        "from": source_label,
        "instruments": instruments,
    }


def run(query: str, context: dict, catalog: dict,
        documents: list) -> dict:
    """One disease through the COA-focused pipeline. Returns a schema."""
    _progress('resolving "%s"' % query)
    schema = {
        "query": query,
        "pipeline_version": PIPELINE_VERSION,
        "run_date": date.today().isoformat(),
        "condition": {},
        "own_coas": [],
        "neighbor_coas": [],
        "coa_blocks": [],
        "status": "",
        "note": "",
    }

    resolved = cr.resolve(query, context)
    schema["condition"] = {
        "query": resolved.get("query", query),
        "status": resolved.get("status", ""),
        "cui": resolved.get("cui", ""),
        "label": resolved.get("label", ""),
        "n_sources": resolved.get("n_sources", 0),
    }

    identified = bool(resolved.get("cui")) or (
        resolved.get("status") in coa.RESOLVED_WITHOUT_CUI)
    if not identified:
        schema["status"] = "UNRESOLVED"
        schema["note"] = (
            f'"{query}" did not resolve to a condition '
            f'({resolved.get("status", "")}). This is not a statement '
            f'that FDA has nothing -- it is a statement that this string '
            f'does not name a condition any authority recognizes.')
        return schema

    # 1. The disease's OWN COAs.
    _progress("checking FDA's COA catalog")
    coa_result = coa.lookup(resolved, catalog, documents)
    own = coa_result.get("coas", []) if (
        coa_result.get("status") == coa.STATUS_FOUND) else []
    schema["own_coas"] = own

    coa_sources = []  # (coa_entry, source_label)
    for entry in own:
        coa_sources.append((entry, "this condition"))

    # 2. If none of its own, look to related catalog conditions.
    if not own and resolved.get("cui"):
        _progress("no COA here -- checking related conditions")
        neighbor_result = nl.find_neighbors(resolved, catalog)
        attached = ncl.attach_coas(neighbor_result, catalog)
        neighbors = attached.get("neighbors", [])
        for n in neighbors:
            for entry in n.get("coas", []) or []:
                label = (f'{n.get("condition", "")} '
                         f'({n.get("relation", "")} of your condition)')
                coa_sources.append((entry, label))
        schema["neighbor_coas"] = [
            n for n in neighbors if n.get("coas")]

    # 3. No COA anywhere -> say so, show nothing on drugs/trials.
    if not coa_sources:
        schema["status"] = "NO_COA_ANYWHERE"
        schema["note"] = (
            "FDA has no COA for this disease, and none for any "
            "structurally related condition in the catalog. There is no "
            "qualified or in-process clinical outcome assessment to "
            "measure outcomes in this disease or a close relative.")
        return schema

    # 4. Per COA instrument: trials + approved drugs.
    for entry, source_label in coa_sources:
        _progress(f'evidence for {entry.get("instrument", "")[:40]}')
        schema["coa_blocks"].append(_coa_block(entry, source_label))

    schema["status"] = "COA_FOUND" if own else "NEIGHBOR_COA_FOUND"
    return schema


_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fda_data", "coa_cache.json")


def _load_cache() -> dict:
    """The pre-built COA cache, or empty. Missing file is fine."""
    if not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:  # noqa: BLE001
        return {}


def run_cached(query: str, context: dict, catalog: dict,
               documents: list, cache: dict = None) -> dict:
    """
    Return the pre-built schema for this query if it is cached, else run
    live. The demo path: cached queries answer instantly; anything not
    pre-built falls through to the live pipeline, unchanged. A query is
    matched case-insensitively on its trimmed text.
    """
    store = _load_cache() if cache is None else cache
    key = query.strip()
    if key in store:
        return store[key]
    for cached_key, schema in store.items():
        if cached_key.strip().lower() == key.lower():
            return schema
    return run(query, context, catalog, documents)


def _drug_name(d: dict) -> str:
    """A drug's display name, flagged if not in RxNorm."""
    flag = "" if d.get("in_rxnorm", True) else " [not in RxNorm]"
    return f'{d["drug"]}{flag}'


def _wrap_names(names: list, indent: str, width: int = 72) -> None:
    """
    Print a comma-separated list of names, wrapped. The first line uses
    `indent` (which may carry a count prefix like "   6  "); every
    continuation line uses a pure-space indent of the SAME width, so the
    names stay left-aligned under each other and a count prefix is not
    repeated or misaligned.
    """
    cont = " " * len(indent)
    line = indent
    first_on_line = True
    for i, name in enumerate(names):
        piece = name + ("," if i < len(names) - 1 else "")
        if not first_on_line and len(line) + 1 + len(piece) > width:
            print(line)
            line = cont + piece
            first_on_line = False
        elif first_on_line:
            line = line + piece
            first_on_line = False
        else:
            line = line + " " + piece
    if line.strip():
        print(line)


def _print_drugs(drug_list: list) -> None:
    """
    Group the approved co-occurring drugs by trial count. Drugs in more
    than one trial are the meaningful set and lead, with equal-count
    drugs sharing a line; the single-trial tail is collapsed into one
    compact wrapped block. NOTHING is capped -- every drug is shown.
    """
    multi = [d for d in drug_list if d.get("trials", 0) >= 2]
    single = [d for d in drug_list if d.get("trials", 0) == 1]

    if multi:
        print(f'         studied across multiple trials '
              f'({len(multi)} drugs):')
        # group by trial count, descending
        by_count: dict = {}
        for d in multi:
            by_count.setdefault(d["trials"], []).append(d)
        for count in sorted(by_count, reverse=True):
            names = [_drug_name(d) for d in
                     sorted(by_count[count], key=lambda x: x["drug"])]
            _wrap_names(names, f'         {count:>2}  ')

    if single:
        print(f'         studied in a single trial '
              f'({len(single)} drugs):')
        names = [_drug_name(d) for d in
                 sorted(single, key=lambda x: x["drug"])]
        _wrap_names(names, '              ')


def _print_schema(schema: dict) -> None:
    cond = schema["condition"]
    label = cond.get("label") or cond.get("query")
    print()
    print("=" * 68)
    print(f'{label} ({cond.get("cui") or cond.get("status")})')
    if cond.get("n_sources"):
        print(f'  identity: {cond["n_sources"]} independent '
              f'vocabularies agreed')
    print("=" * 68)

    if schema["status"] == "UNRESOLVED":
        print()
        print(schema["note"])
        print()
        return

    if schema["status"] == "NO_COA_ANYWHERE":
        print()
        print("COA: NONE, here or nearby.")
        print(schema["note"])
        print()
        return

    # Separate COAs whose instruments were actually USED in trials from
    # those with zero trials. A qualified COA that no trial ever used is
    # a real finding -- FDA vetted an instrument nobody picked up -- but
    # printed as an empty block it just looks like noise, so the unused
    # ones are collapsed into one summary line after the used ones.
    used_blocks = []
    unused_labels = []
    for block in schema["coa_blocks"]:
        any_trials = any(
            item["evidence"]["trials"].get("retrieved", 0) > 0
            for item in block["instruments"])
        if any_trials:
            used_blocks.append(block)
        else:
            unused_labels.append(block["coa_label"])

    for block in used_blocks:
        print()
        mark = "  [QUALIFIED]" if block["qualified"] else ""
        print(f'COA: {block["coa_label"]}{mark}')
        print(f'     from   : {block["from"]}')
        if block["context_of_use"]:
            print(f'     context: {block["context_of_use"][:56]}')
        for item in block["instruments"]:
            ev = item["evidence"]
            tr = ev["trials"]
            print(f'     instrument: {item["instrument"]}')
            print(f'         trials using it: {tr["retrieved"]} '
                  f'({tr["as_primary"]} as primary endpoint)')
            drugs = ev["drugs"]
            drug_list = drugs.get("drugs", [])
            af = drugs.get("approval_filter", "")
            if af == "UNKNOWN":
                print('         drugs: approval set unavailable -- '
                      'filter did not run')
            print(f'         approved drugs in those trials: '
                  f'{len(drug_list)}')
            _print_drugs(drug_list)

    if unused_labels:
        print()
        print(f'OTHER QUALIFIED COAs (no trials found using them): '
              f'{len(unused_labels)}')
        for lab in unused_labels:
            print(f'     {lab}')
        print('     These instruments are qualified/listed but no '
              'trial in the')
        print('     registry used them as an outcome measure -- vetted '
              'but unused.')
    print()


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python3 coa_orchestrator.py "disease name" '
              '[--json]')
        return

    global _VERBOSE
    as_json = "--json" in sys.argv
    _VERBOSE = not as_json
    names = [a for a in sys.argv[1:] if not a.startswith("--")]

    _progress("loading vocabularies and FDA source data")
    context = cr.load_sources()
    catalog = coa.load_catalog()
    documents = coa.load_documents()

    cache = _load_cache()
    if cache:
        print(f"  (using pre-built cache: {len(cache)} conditions)")
    for name in names:
        schema = run_cached(name, context, catalog, documents, cache)
        if as_json:
            print(json.dumps(schema, indent=2))
        else:
            _print_schema(schema)


if __name__ == "__main__":
    main()