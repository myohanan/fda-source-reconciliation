"""
list_coas.py
------------
The full-list / search view over FDA's COA resources. Answers "show me
everything you have" and a variety of filtered queries a front end might
offer.

Two resources, two stages of one pipeline, NO shared key between them:
  - SUBMISSIONS (coa_submissions.csv): every COA submitted to the DDT
    program, at any stage -- the in-motion view. Grouped by stage.
  - COMPENDIUM (coa_compendium.csv): the COAs that completed
    qualification -- the finished view.

Every query leads with a COUNT SUMMARY (the shape of the result), then
the full grouped listing. A front end decides how much of the list to
reveal (expand/collapse, paging); the backend returns both the counts
and the complete data.

Composable filters (stack freely):
  --search "term"   free text across disease / instrument / concept
  --stage "text"    submissions whose qualification stage matches
  --type PRO        COA type (PRO, ClinRO, ObsRO, PerfO, DHT, ...)
  --submissions     only the submissions resource
  --compendium      only the compendium resource
"""

import csv
import os
import sys
from collections import Counter

_BASE = os.path.dirname(os.path.abspath(__file__))
_SUBMISSIONS = os.path.join(_BASE, "fda_data", "coa_submissions.csv")
_COMPENDIUM = os.path.join(_BASE, "fda_data", "coa_compendium.csv")


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def load_submissions():
    return _read(_SUBMISSIONS)


def load_compendium():
    return _read(_COMPENDIUM)


# ---- field accessors (the two files name things differently) ----

def _sub_fields(r):
    return {
        "disease": (r.get("Disease/Condition") or "").strip(),
        "instrument": (r.get("DDT COA Number and Instrument Name")
                       or "").strip(),
        "concept": (r.get("Concept of Interest") or "").strip(),
        "context": (r.get("Context of Use") or "").strip(),
        "type": (r.get("COA Type") or "").strip(),
        "stage": (r.get("Qualification Stage") or "").strip()
        or "(unstated)",
    }


def _comp_fields(r):
    return {
        "disease": (r.get("disease") or "").strip(),
        "instrument": (r.get("coa_tool_type") or "").strip(),
        "concept": (r.get("concept") or "").strip().replace("\n", " "),
        "type": (r.get("coa_tool_type") or "").strip(),
        "division": (r.get("division") or "").strip(),
    }


def _matches(fields, search, ctype):
    if search:
        blob = " ".join(fields.values()).lower()
        if search.lower() not in blob:
            return False
    if ctype:
        if ctype.lower() not in fields.get("type", "").lower():
            return False
    return True


def _apply(subs, comp, search, stage, ctype):
    sub_out = []
    for r in subs:
        f = _sub_fields(r)
        if stage and stage.lower() not in f["stage"].lower():
            continue
        if _matches(f, search, ctype):
            sub_out.append(f)
    comp_out = []
    for r in comp:
        f = _comp_fields(r)
        # stage does not apply to the compendium (all are finished)
        if stage:
            continue
        if _matches(f, search, ctype):
            comp_out.append(f)
    return sub_out, comp_out


# ---- display ----

def _print_summary(sub_out, comp_out, show):
    print("SUMMARY")
    if show in ("both", "submissions"):
        by_stage = Counter(f["stage"] for f in sub_out)
        by_type = Counter(f["type"] for f in sub_out if f["type"])
        print(f"  Submissions matched: {len(sub_out)}")
        for stage, n in by_stage.most_common():
            print(f"      {n:>3}  {stage}")
        if by_type:
            types = ", ".join(f"{t} ({n})"
                              for t, n in by_type.most_common())
            print(f"      by type: {types}")
    if show in ("both", "compendium"):
        print(f"  Compendium matched: {len(comp_out)}")
    print()


def _print_submissions(sub_out):
    if not sub_out:
        return
    by_stage = {}
    for f in sub_out:
        by_stage.setdefault(f["stage"], []).append(f)
    print(f"SUBMISSIONS -- the qualification pipeline ({len(sub_out)})")
    for stage, items in sorted(by_stage.items(),
                               key=lambda kv: -len(kv[1])):
        print(f"  [{stage}]  ({len(items)})")
        for f in sorted(items, key=lambda x: x["instrument"]):
            print(f"    {f['instrument']}")
            print(f"        disease: {f['disease']}   "
                  f"type: {f['type']}")
        print()


def _print_compendium(comp_out):
    if not comp_out:
        return
    print(f"COMPENDIUM -- completed qualification ({len(comp_out)})")
    for f in sorted(comp_out, key=lambda x: x["disease"]):
        print(f"  {f['disease']}")
        print(f"      type: {f['type']}   division: {f['division']}")
        if f["concept"]:
            print(f"      concept: {f['concept']}")
    print()


def main():
    argv = sys.argv[1:]
    search = stage = ctype = None
    show = "both"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--search" and i + 1 < len(argv):
            search = argv[i + 1]
            i += 2
        elif a == "--stage" and i + 1 < len(argv):
            stage = argv[i + 1]
            i += 2
        elif a == "--type" and i + 1 < len(argv):
            ctype = argv[i + 1]
            i += 2
        elif a == "--submissions":
            show = "submissions"
            i += 1
        elif a == "--compendium":
            show = "compendium"
            i += 1
        else:
            # bare word = search term
            search = a
            i += 1

    subs = load_submissions() if show in ("both", "submissions") else []
    comp = load_compendium() if show in ("both", "compendium") else []
    sub_out, comp_out = _apply(subs, comp, search, stage, ctype)

    print("=" * 70)
    print("FDA CLINICAL OUTCOME ASSESSMENTS")
    q = []
    if search:
        q.append(f'search="{search}"')
    if stage:
        q.append(f'stage~"{stage}"')
    if ctype:
        q.append(f'type={ctype}')
    print("  query: " + (", ".join(q) if q else "everything"))
    print("=" * 70)
    print()
    _print_summary(sub_out, comp_out, show)
    if show in ("both", "submissions"):
        _print_submissions(sub_out)
    if show in ("both", "compendium"):
        _print_compendium(comp_out)


if __name__ == "__main__":
    main()