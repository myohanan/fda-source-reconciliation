"""
list_coas.py
------------
FDA Source Reconciliation
Independent Women's Center for Better Health

The full-list / search view over FDA's COA resources. Answers "show me
everything you have" and a variety of filtered queries a front end might
offer.

Three resources, no shared key between them:
  - QUALIFIED (qualified_coas.csv): the COAs that completed
    qualification -- the finished view. The 7 that cleared the bar.
  - SUBMISSIONS (coa_submissions.csv): every COA submitted to the DDT
    program, at any stage -- the in-motion view. Grouped by stage.
  - COMPENDIUM (coa_compendium.csv): the 2021 disease-to-endpoint-to-
    approval snapshot. Hand-compiled, frozen June 2021.

Every query leads with a COUNT SUMMARY (the shape of the result), then
the full grouped listing. A front end decides how much of the list to
reveal (expand/collapse, paging); the backend returns both the counts
and the complete data.

Composable filters (stack freely):
  --search "term"   free text across disease / instrument / concept
  --stage "text"    submissions whose qualification stage matches
  --type PRO        COA type (PRO, ClinRO, ObsRO, PerfO, DHT, ...)
  --qualified       only the qualified resource
  --submissions     only the submissions resource
  --compendium      only the compendium resource
"""

import csv
import json
import os
import sys
from collections import Counter

import condition_resolver as cr
import hierarchy_matcher as hm

_BASE = os.path.dirname(os.path.abspath(__file__))
_QUALIFIED = os.path.join(_BASE, "fda_data", "qualified_coas.csv")
_SUBMISSIONS = os.path.join(_BASE, "fda_data", "coa_submissions.csv")
_COMPENDIUM = os.path.join(_BASE, "fda_data", "coa_compendium.csv")


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def load_qualified():
    return _read(_QUALIFIED)


def load_submissions():
    return _read(_SUBMISSIONS)


def load_compendium():
    return _read(_COMPENDIUM)


# ---- field accessors (the files name things differently) ----

def _qual_fields(r):
    return {
        "disease": (r.get("Disease/Condition") or "").strip(),
        "instrument": (r.get("DDT COA Number and Instrument Name")
                       or "").strip(),
        "concept": (r.get("Concept of Interest") or "").strip(),
        "context": (r.get("Context of Use") or "").strip(),
        "type": (r.get("COA Type") or "").strip(),
    }


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


# Disease name -> CUI, built ONCE by build_disease_cui.py. Loaded at
# startup as an instant dict; search does lookups, never live network
# resolution. A missing map file degrades to substring matching.
_DISEASE_CUI_PATH = os.path.join(_BASE, "fda_data",
                                 "coa_disease_cui.json")
_DISEASE_CUI = {}
if os.path.exists(_DISEASE_CUI_PATH):
    with open(_DISEASE_CUI_PATH, encoding="utf-8") as _fh:
        _DISEASE_CUI = json.load(_fh)


def _cui_for(name):
    """The CUI for a catalog disease name, from the prebuilt map.

    Instant dict lookup, no network. The query term is resolved live
    (once, cached) only when it is not already a catalog name.
    """
    if not name:
        return ""
    if name in _DISEASE_CUI:
        return _DISEASE_CUI[name]
    # The search query may not be a verbatim catalog name; resolve it
    # live once (condition_resolver caches to disk). Catalog ROWS always
    # hit the map above, so this runs at most once per search. resolve
    # needs the mondo context from load_sources(); build it once, lazily.
    try:
        r = cr.resolve(name, _resolver_context())
        cui = (r.get("cui", "")
               if r.get("status") == cr.STATUS_RESOLVED else "")
    except Exception:  # noqa: BLE001
        cui = ""
    _DISEASE_CUI[name] = cui
    return cui


_CONTEXT = None


def _resolver_context():
    """Build the resolver's mondo context once, lazily (only if a live
    resolve is actually needed for a non-catalog query term)."""
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = cr.load_sources()
    return _CONTEXT


# How each structural relation is shown to the user. This is the
# thesis: a search resolves to an identity, and the relation to each
# catalog row is READ from the published vocabularies (via
# hierarchy_matcher.relate) -- never matched by string, never forced to
# exact identity. The user sees WHY each row surfaced and decides what
# to pull. UNRELATED / NO_HIERARCHY are not structural matches and do
# not surface through the hierarchy path.
_REL_LABEL = {
    hm.REL_EXACT: "exact",
    hm.REL_CHILD: "child",
    hm.REL_DESCENDANT: "child",
    hm.REL_PARENT: "parent",
    hm.REL_ANCESTOR: "parent",
    hm.REL_SIBLING: "sibling",
}


def _relation_label(fields, search_cui):
    """The relation of this row's disease to the query, or None.

    None means no structural relationship (UNRELATED / NO_HIERARCHY) or
    the row's disease did not resolve -- either way it does not surface
    through the hierarchy path.
    """
    if not search_cui:
        return None
    row_cui = _cui_for(fields.get("disease", ""))
    if not row_cui:
        return None
    rel = hm.relate(search_cui, row_cui).get("relation")
    return _REL_LABEL.get(rel)


def _matches(fields, search, ctype, search_cui=None):
    """Return (ok, relation_label). relation_label is the hierarchy
    relation of the row to the query (or None when there is no search,
    or the match came from the substring fallback)."""
    rel_label = None
    if search:
        matched = False
        if search_cui:
            # HIERARCHY MATCH: keep the row when it is the same
            # condition or structurally related; carry the relation so
            # the display can show it. "small cell lung cancer" and
            # "non-small cell lung cancer" surface each other as
            # [sibling] -- shown and labeled, not merged, not hidden.
            rel_label = _relation_label(fields, search_cui)
            if rel_label is not None:
                matched = True
        else:
            # FALLBACK: the query did not resolve to a condition (a typo
            # or a non-disease term). Fall back to substring so search
            # still does something. This is the exception, not the path.
            blob = " ".join(fields.values()).lower()
            if search.lower() in blob:
                matched = True
        if not matched:
            return False, None
    if ctype:
        if ctype.lower() not in fields.get("type", "").lower():
            return False, None
    return True, rel_label


def _apply(qual, subs, comp, search, stage, ctype):
    search_cui = _cui_for(search) if search else None
    qual_out = []
    for r in qual:
        f = _qual_fields(r)
        if stage:
            continue
        ok, rel = _matches(f, search, ctype, search_cui)
        if ok:
            f["_relation"] = rel
            qual_out.append(f)
    sub_out = []
    for r in subs:
        f = _sub_fields(r)
        if stage and stage.lower() not in f["stage"].lower():
            continue
        ok, rel = _matches(f, search, ctype, search_cui)
        if ok:
            f["_relation"] = rel
            sub_out.append(f)
    comp_out = []
    for r in comp:
        f = _comp_fields(r)
        if stage:
            continue
        ok, rel = _matches(f, search, ctype, search_cui)
        if ok:
            f["_relation"] = rel
            comp_out.append(f)
    return qual_out, sub_out, comp_out


# ---- display ----

def _rel_tag(f):
    """The relationship of this row to what was searched. Empty for an
    exact match (the searched condition's own COA); otherwise names the
    relation, so a child/parent/sibling COA is never read as belonging
    to the searched disease. This is the thesis made visible: the user
    sees WHY each row surfaced and whose COA it actually is."""
    rel = f.get("_relation")
    if not rel or rel == "exact":
        return ""
    return f"   [{rel} of your search]"


def _print_summary(qual_out, sub_out, comp_out, show):
    print("SUMMARY")
    if show in ("both", "qualified"):
        print(f"  Qualified matched: {len(qual_out)}")
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


def _print_qualified(qual_out):
    if not qual_out:
        return
    print(f"QUALIFIED -- completed qualification ({len(qual_out)})")
    for f in sorted(qual_out, key=lambda x: x["instrument"]):
        print(f"    {f['instrument']}")
        print(f"        disease: {f['disease']}{_rel_tag(f)}")
        print(f"        type: {f['type']}")
        if f["concept"]:
            print(f"        concept: {f['concept']}")
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
            print(f"        disease: {f['disease']}{_rel_tag(f)}")
            print(f"        type: {f['type']}")
        print()


def _print_compendium(comp_out):
    if not comp_out:
        return
    print(f"COMPENDIUM -- completed qualification ({len(comp_out)})")
    for f in sorted(comp_out, key=lambda x: x["disease"]):
        print(f"  {f['disease']}{_rel_tag(f)}")
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
        elif a == "--qualified":
            show = "qualified"
            i += 1
        elif a == "--submissions":
            show = "submissions"
            i += 1
        elif a == "--compendium":
            show = "compendium"
            i += 1
        else:
            search = a
            i += 1

    qual = load_qualified() if show in ("both", "qualified") else []
    subs = load_submissions() if show in ("both", "submissions") else []
    comp = load_compendium() if show in ("both", "compendium") else []
    qual_out, sub_out, comp_out = _apply(
        qual, subs, comp, search, stage, ctype)

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
    _print_summary(qual_out, sub_out, comp_out, show)
    if show in ("both", "qualified"):
        _print_qualified(qual_out)
    if show in ("both", "submissions"):
        _print_submissions(sub_out)
    if show in ("both", "compendium"):
        _print_compendium(comp_out)


if __name__ == "__main__":
    main()