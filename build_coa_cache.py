"""
build_coa_cache.py
------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Pre-build the COA-orchestrator result for every catalog condition and a
set of demo queries, so the live demo reads from disk instantly instead
of waiting on ClinicalTrials.gov and RxNav.

WHY

coa_orchestrator runs live: endpoint_search hits ClinicalTrials.gov,
and coa_drug_link resolves every trial intervention through RxNav. For
a single instrument that is minutes on a cold cache. In a demo, minutes
of silence reads as broken. So the slow work is done ONCE, offline, and
written to fda_data/coa_cache.json; the orchestrator reads the cached
schema when the query is present and runs live otherwise.

WHAT IT BUILDS

  1. All catalog conditions in fda_data/coa_resolution.csv (the 54).
     Every one has a COA, so each yields a full block. The seven
     trial-population conditions (recovery from surgery and anesthesia,
     the bacterial pneumonias, etc.) yield their honest category-fact
     result -- not a disease entity, not resolvable as one -- and that
     answer is cached too.
  2. DEMO_QUERIES -- the everyday terms a person actually types, which
     are NOT catalog conditions: congestive heart failure (lands on a
     neighbor's COA), lung cancer (lands on related conditions' COAs),
     breast cancer and Gaucher disease (clean "no COA anywhere"). These
     are the cases FDA's own page cannot answer, so they are the demo.

RESUMABLE. A condition already in the cache is skipped, so an
interrupted run (Ctrl-C, network drop) is continued by re-running. The
shared drug_resolve_cache.json means intervention resolutions done for
one condition are reused by the next -- heart-failure drugs recur
across heart-failure conditions -- so later conditions build faster.

Progress is printed per condition, because a multi-hour build must show
it is alive, not hung -- the same principle the orchestrators use for
their live runs.
"""

import csv
import json
import os
import time

import coa_lookup as coa
import condition_resolver as cr
import coa_orchestrator as orch

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
RESOLUTION_CSV = os.path.join(DATA_DIR, "coa_resolution.csv")
CACHE_PATH = os.path.join(DATA_DIR, "coa_cache.json")

# The everyday terms a person types that are NOT catalog conditions --
# the demo's whole point. Edit freely.
DEMO_QUERIES = [
    "congestive heart failure",
    "lung cancer",
    "breast cancer",
    "Gaucher disease",
]


def _catalog_condition_names() -> list:
    """The catalog condition display names from coa_resolution.csv."""
    names: list = []
    if not os.path.exists(RESOLUTION_CSV):
        print(f"WARNING: {RESOLUTION_CSV} not found; catalog conditions "
              f"skipped.")
        return names
    with open(RESOLUTION_CSV, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        # The condition name column: try common headers.
        field = None
        for cand in ("condition", "catalog_condition", "name",
                     "coa_condition", "query"):
            if reader.fieldnames and cand in reader.fieldnames:
                field = cand
                break
        if field is None:
            # Fall back to the first column.
            field = reader.fieldnames[0] if reader.fieldnames else None
        if field is None:
            return names
        for row in reader:
            value = (row.get(field) or "").strip()
            if value and value not in names:
                names.append(value)
    return names


def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(cache: dict) -> None:
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(cache, handle)
    os.replace(tmp, CACHE_PATH)


def main() -> None:
    print("Loading vocabularies and FDA source data...")
    context = cr.load_sources()
    catalog = coa.load_catalog()
    documents = coa.load_documents()

    targets: list = []
    for name in _catalog_condition_names():
        if name not in targets:
            targets.append(name)
    for name in DEMO_QUERIES:
        if name not in targets:
            targets.append(name)

    cache = _load_cache()
    total = len(targets)
    print(f"{total} conditions to build "
          f"({len(cache)} already cached, will be skipped).")
    print("-" * 68)

    for i, name in enumerate(targets, 1):
        if name in cache:
            print(f"  [{i}/{total}] SKIP (cached): {name}")
            continue
        t0 = time.time()
        print(f"  [{i}/{total}] building: {name} ...", flush=True)
        try:
            schema = orch.run(name, context, catalog, documents)
        except Exception as exc:  # noqa: BLE001
            print(f"      ERROR: {type(exc).__name__}: {exc}")
            continue
        cache[name] = schema
        _save_cache(cache)  # write after each, so a crash keeps work
        dt = time.time() - t0
        status = schema.get("status", "")
        print(f"      done ({status}) in {dt:.0f}s")

    print("-" * 68)
    print(f"Wrote {CACHE_PATH}")
    print(f"  {len(cache)} conditions cached.")


if __name__ == "__main__":
    main()