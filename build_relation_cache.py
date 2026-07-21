"""
build_relation_cache.py
FDA Source Reconciliation
Independent Women's Center for Better Health

Warm hierarchy_relation_cache.json so relate() never goes live during a
list_coas search. relate() serves SNOMED/ICD10CM/NCI/MDR from local
indexes, but MeSH falls through to the live UMLS API with a rate-limit
pause -- so an un-warmed search pays a network round-trip per uncached
MeSH code and appears to hang. This precomputes the relations once.

For every unique disease CUI in coa_disease_cui.json (used both as the
things a person searches and as the catalog rows), compute relate()
against every other unique disease CUI. The MeSH lookups are cached as a
side effect; afterwards search reads the warm cache and is instant.

Run once. Re-run only if the disease set or the code index changes.
"""

import json
import os
import sys
import time

import hierarchy_matcher as hm

_BASE = os.path.dirname(os.path.abspath(__file__))
_MAP = os.path.join(_BASE, "fda_data", "coa_disease_cui.json")


def _unique_cuis():
    with open(_MAP, encoding="utf-8") as fh:
        mapping = json.load(fh)
    cuis = sorted({c for c in mapping.values() if c})
    return cuis


def main():
    cuis = _unique_cuis()
    n = len(cuis)
    total = n * n
    print(f"{n} unique disease CUIs -> {total} relation pairs to warm.")
    print("SNOMED/ICD10CM/NCI/MDR are local; MeSH hits the network once")
    print("per uncached code (with a pause). This runs once.\n")

    t0 = time.time()
    done = 0
    for i, a in enumerate(cuis, 1):
        for b in cuis:
            if a == b:
                continue
            hm.relate(a, b)  # side effect: caches all 5 sources
            done += 1
        if i % 5 == 0 or i == n:
            dt = time.time() - t0
            rate = done / dt if dt else 0
            left = (total - done) / rate if rate else 0
            print(f"  [{i}/{n} conditions]  {done} pairs  "
                  f"{dt:.0f}s elapsed  ~{left:.0f}s left", flush=True)

    print(f"\nwarmed {done} pairs in {time.time()-t0:.0f}s")

    # VERIFY known pairs before trusting the warm.
    print("\nverification (known-good relations):")
    checks = [
        ("C0018801", "C0264716", "heart failure -> chronic HF",
         {"CHILD", "PARENT", "SIBLING", "EXACT"}),
        ("C0149925", "C0007131", "small cell -> NSCLC",
         {"SIBLING"}),
        ("C0242379", "C0010674", "lung cancer -> cystic fibrosis",
         {"UNRELATED"}),
    ]
    ok_all = True
    for a, b, label, expected in checks:
        rel = hm.relate(a, b).get("relation")
        ok = rel in expected
        ok_all = ok_all and ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<38} -> {rel}")
    print("\nWARM CLEAN" if ok_all else "\nWARM SUSPECT - re-run")


if __name__ == "__main__":
    main()