"""
build_disease_cui.py
FDA Source Reconciliation
Independent Women's Center for Better Health

Resolve every unique disease name in the three COA resources ONCE and
write fda_data/coa_disease_cui.json as { "<disease name>": "<CUI>" }.

list_coas uses this map to match a search by CONDITION IDENTITY instead
of by substring -- so "small cell lung cancer" (C0149925) does not match
"non-small cell lung cancer" (C0007131). The resolution is done here,
once, at build time; search then does instant dict lookups with no live
network calls. Re-run only when the catalog CSVs change.
"""

import csv
import json
import os
import sys

import condition_resolver as cr

_BASE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_BASE, "fda_data")
_QUALIFIED = os.path.join(_DATA, "qualified_coas.csv")
_SUBMISSIONS = os.path.join(_DATA, "coa_submissions.csv")
_COMPENDIUM = os.path.join(_DATA, "coa_compendium.csv")
_OUT = os.path.join(_DATA, "coa_disease_cui.json")


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _disease_names():
    names = set()
    for r in _read(_QUALIFIED):
        n = (r.get("Disease/Condition") or "").strip()
        if n:
            names.add(n)
    for r in _read(_SUBMISSIONS):
        n = (r.get("Disease/Condition") or "").strip()
        if n:
            names.add(n)
    for r in _read(_COMPENDIUM):
        n = (r.get("disease") or "").strip()
        if n:
            names.add(n)
    return sorted(names)


def main():
    names = _disease_names()
    print("loading resolver sources (mondo context)...")
    context = cr.load_sources()
    print(f"resolving {len(names)} unique disease names (once)...")
    mapping = {}
    for i, name in enumerate(names, 1):
        try:
            r = cr.resolve(name, context)
            cui = (r.get("cui", "")
                   if r.get("status") == cr.STATUS_RESOLVED else "")
        except Exception as e:  # noqa: BLE001
            cui = ""
            print(f"  [{i}/{len(names)}] ERROR {name!r}: {e!r}")
            continue
        mapping[name] = cui
        tag = cui if cui else "(unresolved)"
        print(f"  [{i}/{len(names)}] {name[:44]:<44} -> {tag}")

    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    resolved = sum(1 for v in mapping.values() if v)
    print(f"\nwrote {_OUT}")
    print(f"  {resolved}/{len(names)} resolved to a CUI, "
          f"{len(names) - resolved} unresolved")


if __name__ == "__main__":
    main()