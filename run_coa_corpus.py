"""
run_coa_corpus.py
-----------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Runs condition_resolver against the FULL FDA COA catalog.

This is the validation corpus, and it is validatable BY HAND. The COA
catalog is 54 conditions. Every one can be checked by a person -- not
sampled, not estimated, VERIFIED. That is only possible because the
catalog is nearly empty, which is the same fact that makes the catalog
a problem. The thinness that is the finding is also what makes the
validation airtight.

Same discipline as the hundred hand-built rare-disease cases: bound the
problem small enough to know the answer, then build the thing that
scales.

OUTPUTS
  fda_data/coa_resolution.csv    one row per condition
  fda_data/coa_near_misses.csv   every refusal, with its reason

The near-miss file is the calibration instrument. It has already
overturned two design decisions and confirmed one. Read it before
loosening any rule.
"""

import csv
import os
import time

import condition_resolver as cr

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")

SUBMISSIONS_CSV = os.path.join(DATA_DIR, "coa_submissions.csv")
QUALIFIED_CSV = os.path.join(DATA_DIR, "qualified_coas.csv")
RESOLUTION_CSV = os.path.join(DATA_DIR, "coa_resolution.csv")
NEAR_MISS_CSV = os.path.join(DATA_DIR, "coa_near_misses.csv")

PAUSE_SECONDS = 0.1

RESOLUTION_COLUMNS = [
    "condition", "normalized", "status", "cui", "label",
    "semantic_types", "n_sources", "atom_count", "sources",
    "mondo_id", "hierarchy_available", "candidates",
]

NEAR_MISS_COLUMNS = ["condition", "source", "reason", "candidate"]

# Every way a string can land. The three RESOLVED_* statuses are
# successes -- each names WHICH AUTHORITY resolved it, because the
# authority is part of the answer, not an implementation detail.
RESOLVED_STATUSES = [
    cr.STATUS_RESOLVED,
    cr.STATUS_TRIAL_POPULATION,
    cr.STATUS_MULTINAME,
    cr.STATUS_GUIDANCE_DEFINED,
]

STATUS_ORDER = RESOLVED_STATUSES + [
    cr.STATUS_CONFLICT,
    cr.STATUS_NOT_CONDITION,
    cr.STATUS_UNRESOLVED,
]


def load_conditions() -> list[str]:
    """Every distinct Disease/Condition string in the COA catalog."""
    seen = set()
    for path in (SUBMISSIONS_CSV, QUALIFIED_CSV):
        if not os.path.exists(path):
            print(f"WARNING: {path} not found; skipping")
            continue
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                value = (row.get("Disease/Condition") or "").strip()
                if value:
                    seen.add(value)
    return sorted(seen)


def main() -> None:
    conditions = load_conditions()
    print(f"Loaded {len(conditions)} distinct COA conditions.")

    if not cr.UMLS_API_KEY:
        print("ERROR: no UMLS_API_KEY in .env.")
        return

    context = cr.load_sources()
    print(f"MONDO hierarchy index: {len(context['mondo_terms'])} terms")
    print()

    results = []
    for position, condition in enumerate(conditions, start=1):
        results.append(cr.resolve(condition, context))
        if position % 10 == 0 or position == len(conditions):
            print(f"  {position}/{len(conditions)}")
        time.sleep(PAUSE_SECONDS)

    counts = {status: 0 for status in STATUS_ORDER}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1

    total = len(results)
    print()
    print("=== STATUS ===")
    for status in STATUS_ORDER:
        print(f"  {status:<20} {counts[status]:>3}  "
              f"{'#' * counts[status]}")
    print(f"  {'-' * 44}")
    resolved = sum(counts[s] for s in RESOLVED_STATUSES)
    print(f"  RESOLVED (any authority): {resolved}/{total} "
          f"({100 * resolved // total if total else 0}%)")

    print()
    print("=== CONVERGENCE (how many vocabularies agreed) ===")
    for result in sorted(results, key=lambda r: -r["n_sources"])[:8]:
        if result["status"] in RESOLVED_STATUSES:
            print(f"  {result['n_sources']:>2} vocabs  "
                  f"{result['query'][:44]:<44} {result['cui']}")

    with open(RESOLUTION_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESOLUTION_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow({
                "condition": result["query"],
                "normalized": result["normalized"],
                "status": result["status"],
                "cui": result["cui"],
                "label": result["label"],
                "semantic_types": "|".join(result["semantic_types"]),
                "n_sources": result["n_sources"],
                "atom_count": result["atom_count"],
                "sources": "|".join(result["sources"]),
                "mondo_id": result["mondo_id"],
                "hierarchy_available": result["hierarchy_available"],
                "candidates": "|".join(result["candidates"]),
            })

    misses = 0
    with open(NEAR_MISS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NEAR_MISS_COLUMNS)
        writer.writeheader()
        for result in results:
            for miss in result["near_misses"]:
                writer.writerow({
                    "condition": result["query"],
                    "source": miss["source"],
                    "reason": miss["reason"],
                    "candidate": miss["candidate"],
                })
                misses += 1

    print()
    print(f"Wrote {total} rows to {RESOLUTION_CSV}")
    print(f"Wrote {misses} near-misses to {NEAR_MISS_CSV}")

    print()
    print("=== NEEDS A HUMAN ===")
    for result in results:
        if result["status"] in RESOLVED_STATUSES:
            continue
        detail = ""
        if result["candidates"]:
            detail = f"candidates={result['candidates']}"
        print(f"  [{result['status']}] {result['query']}  {detail}")


if __name__ == "__main__":
    main()
