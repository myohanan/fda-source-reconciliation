"""
hierarchy_matcher.py
--------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Given two RESOLVED conditions, what is their relation?

One job. It does not resolve identity (condition_resolver does that),
does not look at the COA catalog (coa_lookup does that), and does not
decide whether a COA is APPLICABLE to a population -- that is a
regulatory and clinical judgment, and no tool here makes it.

WHY THIS EXISTS

coa_lookup's answer for congestive heart failure is technically true and
practically useless. It says NO COA -- and the KCCQ, qualified and used
in 1,029 trials with 117 primary endpoints, sits one SIBLING away under
the same parent.

That is not a corner case. It is the TYPICAL case: FDA's catalog holds
54 conditions and medicine holds thousands, so almost every real query
lands on an empty cell. If the only answer is "nothing," the tool is
honest and nearly useless.

The hierarchy is what makes "nothing" INFORMATIVE: nothing for your
condition, but here is what is nearby and here is the RELATIONSHIP.

NAVIGATION, NOT RECOMMENDATION

Surfacing a neighbor is not authorizing its use. Whether the KCCQ
applies to an acute decompensated population is a REGULATORY question --
its qualified context of use is "stage C & D heart failure, NYHA Classes
I-IV, HFpEF or HFrEF," and that is FDA's determination to make, not this
tool's.

The RELATION LABEL is what keeps it navigation. "SIBLING" is
information. "You can use this" would be advice, and this tool has no
standing to give it.

SIX SOURCES, BECAUSE ONE IS NOT ENOUGH -- AND THIS WAS MEASURED

A first version of this tool was built on SNOMED alone -- not because
SNOMED was the right authority, but because it was already on hand. The
coverage gaps were then defended rather than measured. That was wrong,
and it is the same error the resolver made with MONDO before the corpus
corrected it.

So it was measured. Across all 54 FDA COA conditions:

    SNOMED    47/54  (87%)
    MeSH      43/54  (79%)
    NCIt      43/54  (79%)
    MONDO     38/54  (70%)
    ICD-10CM  36/54  (66%)
    MedDRA    31/54  (57%)

No source covers everything. 19 conditions have a parent in ALL SIX; 18
more in five. So the hierarchy is asked of every source, and agreement
across them is the confidence -- exactly as it is for identity.

NO_HIERARCHY IS A REAL STATE, NOT A SILENT ZERO

Seven of the 54 conditions have NO parent in ANY of the six sources:

    Acute Bacterial Skin and Skin Structure Infection
    Community-Acquired Bacterial Pneumonia
    Hospital-acquired Bacterial Pneumonia
    Non-Cystic Fibrosis Bronchiectasis
    Dystrophinopathy
    Acute Bacterial Exacerbation of Chronic Bronchitis in COPD
    Recovery from surgery and anesthesia

That is not a coverage gap. IT IS A CATEGORY FACT. These are TRIAL
ENROLLMENT DEFINITIONS, not disease entities -- they resolved through
ClinicalTrials.gov, not through any vocabulary. A trial population has
no taxonomic parent because it is not the kind of thing that has one.

So the tool REPORTS that, plainly. "No neighbors found" and "this has no
taxonomic parent anywhere, because it is a trial population" are
different facts, and a user cannot tell them apart from a blank. That
confusion -- failed check versus real absence -- is the failure this
whole architecture exists to prevent, and a silent hierarchy would have
introduced it through the tool meant to add value.

SHARED ANCESTRY IS NOT A RELATION

Every concept shares an ancestor: the root. Congestive and chronic heart
failure share TWENTY SNOMED ancestors, including "Disorder of thorax"
and "Functional finding." Reporting that as a relationship would be
noise dressed as insight.

Only STRUCTURAL, IMMEDIATE relations are reported -- parent, child,
sibling -- or true ancestry within a bounded depth. A relation without
distance is a statement that two things are both diseases.

THE CASE THIS WAS BUILT FOR

    congestive heart failure  C0018802
        SNOMED 42343007, parents: Heart failure,
                                  Disorder of cardiac ventricle
    chronic heart failure     C0264716
        SNOMED 48447003, parents: Heart failure,
                                  Chronic heart disease

SIBLINGS. Both children of Heart failure. Neither subsumes the other --
verified in both directions.

A synonym list would collapse them, hand the developer FDA's COA, and
never say the concepts differ. This tool surfaces the neighbor and NAMES
THE RELATIONSHIP.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

import condition_resolver as cr

UMLS = "https://uts-ws.nlm.nih.gov/rest"
HEADERS = {"User-Agent": "fda-recon/1.0", "Accept": "application/json"}
PAUSE = 0.12
TIMEOUT = 40

_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fda_data")
_CACHE_PATH = os.path.join(_CACHE_DIR,
                           "hierarchy_relation_cache.json")
_KEY_SEP = "|"

# SNOMED's is-a hierarchy, built once from the RF2 release by
# build_snomed_index.py and read from disk instead of fetched live.
# SNOMED is the source hierarchy_matcher walks for neighbors; serving it
# locally removes the per-neighbor UMLS call that made a no-COA query
# spend ~110 seconds over the network. The other five sources still go
# live -- only SNOMED is on disk. If the index file is absent, the
# SNOMED path falls through to the live API exactly as before.
_SNOMED_SAB = "SNOMEDCT_US"
_SNOMED_INDEX_PATH = os.path.join(_CACHE_DIR, "snomed_index.json")
_snomed_index: dict = {}


def _load_snomed_index() -> None:
    """
    Seed the SNOMED is-a index from disk, if present. A missing file is
    not an error -- the SNOMED path degrades to the live API, same as
    before this index existed.
    """
    if not os.path.exists(_SNOMED_INDEX_PATH):
        return
    try:
        with open(_SNOMED_INDEX_PATH, encoding="utf-8") as handle:
            _snomed_index.update(json.load(handle))
    except Exception:  # noqa: BLE001
        _snomed_index.clear()


_load_snomed_index()


# SNOMED concepts that have at least one DEFINING attribute (finding
# site, associated morphology, etc.) versus pure GROUPERS that have
# none. Built by build_defining_attributes.py from the RF2 Relationship
# file. The sibling gate uses it: a sibling is inferred THROUGH a shared
# parent, and is only meaningful if that parent is a real disease family
# ("Heart failure", 3 defining attributes) rather than a classification
# grouper ("Autosomal recessive hereditary disorder", 0 attributes). A
# code present in this map is DEFINED; absent means grouper. A missing
# file disables the gate (behaves as before), never crashes.
_DEFINED_PATH = os.path.join(_CACHE_DIR, "snomed_defined.json")
_snomed_defined: dict = {}


def _load_defined_index() -> None:
    """Seed the defining-attributes map from disk. Missing file is OK."""
    if not os.path.exists(_DEFINED_PATH):
        return
    try:
        with open(_DEFINED_PATH, encoding="utf-8") as handle:
            _snomed_defined.update(json.load(handle))
    except Exception:  # noqa: BLE001
        _snomed_defined.clear()


_load_defined_index()


def _snomed_ancestors(code: str) -> list[tuple[str, str]]:
    """
    All ancestors of a SNOMED code, walked transitively up the is-a
    links to the root. The index stores only IMMEDIATE parents; the live
    API returned the full ancestor chain, so this reproduces that by
    walking parents of parents. Cycles cannot occur in a well-formed
    is-a hierarchy, but a seen-set guards against a malformed one.
    """
    out: list[tuple[str, str]] = []
    seen = {code}
    frontier = [code]
    while frontier:
        current = frontier.pop()
        node = _snomed_index.get(current)
        if not node:
            continue
        for parent in node["parents"]:
            if parent in seen:
                continue
            seen.add(parent)
            pname = _snomed_index.get(parent, {}).get("name", "")
            out.append((parent, pname))
            frontier.append(parent)
    return out


def _snomed_relatives(code: str, kind: str) -> list[tuple[str, str]]:
    """
    parents / children / ancestors of a SNOMED code, from the local
    index -- the same shape the live _relatives returns: (id, name)
    tuples. No network, no pause.
    """
    if kind == "ancestors":
        return _snomed_ancestors(code)
    node = _snomed_index.get(code)
    if not node:
        return []
    ids = node.get(kind, [])
    return [(i, _snomed_index.get(i, {}).get("name", "")) for i in ids]


# Local is-a hierarchy for the sources with no tree of their own --
# ICD10CM, NCI, MDR -- built from the UMLS release by
# build_hierarchy_index.py. When present, _relatives reads parents,
# children, and ancestors from here instead of the live API, the same
# way SNOMED is served from its own index. A missing file is fine: the
# affected source degrades to the live API, unchanged. (MeSH is served
# through the live API for now; SNOMED has its own index above.)
_HIERARCHY_INDEX_PATH = os.path.join(_CACHE_DIR, "hierarchy_index.json")
_hierarchy_index: dict = {}


def _load_hierarchy_index() -> None:
    """Seed the local hierarchy index from disk. Missing file is fine."""
    if not os.path.exists(_HIERARCHY_INDEX_PATH):
        return
    try:
        with open(_HIERARCHY_INDEX_PATH, encoding="utf-8") as handle:
            _hierarchy_index.update(json.load(handle))
    except Exception:  # noqa: BLE001
        _hierarchy_index.clear()


_load_hierarchy_index()


def _local_ancestors(sab_index: dict,
                     code: str) -> list[tuple[str, str]]:
    """
    All ancestors of a code, walked transitively up the parent edges to
    the root -- the same reproduction of the live API's full ancestor
    chain that _snomed_ancestors does for SNOMED. The index stores only
    IMMEDIATE parents; ancestors are parents-of-parents. A seen-set
    guards a malformed hierarchy against cycles.
    """
    parents_map = sab_index.get("parents", {})
    names = sab_index.get("names", {})
    out: list[tuple[str, str]] = []
    seen = {code}
    frontier = [code]
    while frontier:
        current = frontier.pop()
        for parent in parents_map.get(current, []):
            if parent in seen:
                continue
            seen.add(parent)
            out.append((parent, names.get(parent, "")))
            frontier.append(parent)
    return out


def _local_relatives(sab: str, code: str,
                     kind: str) -> list[tuple[str, str]]:
    """
    parents / children / ancestors of a code from the local hierarchy
    index -- the same (id, name) shape the live _relatives returns. No
    network, no pause.
    """
    sab_index = _hierarchy_index.get(sab)
    if not sab_index:
        return []
    if kind == "ancestors":
        return _local_ancestors(sab_index, code)
    names = sab_index.get("names", {})
    # "parents" -> the parents map; "children" -> the children map.
    edge_map = sab_index.get(kind, {})
    return [(c, names.get(c, "")) for c in edge_map.get(code, [])]


# Every source with a real is-a hierarchy, and its UMLS abbreviation.
# Coverage measured across FDA's 54 COA conditions -- see the docstring.
SOURCES = {
    "SNOMED": "SNOMEDCT_US",
    "MESH": "MSH",
    "NCIT": "NCI",
    "ICD10CM": "ICD10CM",
    "MEDDRA": "MDR",
}

REL_EXACT = "EXACT"
REL_PARENT = "PARENT"
REL_CHILD = "CHILD"
REL_SIBLING = "SIBLING"
REL_ANCESTOR = "ANCESTOR"
REL_DESCENDANT = "DESCENDANT"
REL_UNRELATED = "UNRELATED"
REL_NO_HIERARCHY = "NO_HIERARCHY"

# A structural relation from ANY source outranks UNRELATED from the
# rest: silence is not disagreement. A source that does not carry a
# concept has not voted against a relation -- it has not voted.
_RANK = {
    REL_EXACT: 0,
    REL_PARENT: 1,
    REL_CHILD: 1,
    REL_SIBLING: 2,
    REL_ANCESTOR: 3,
    REL_DESCENDANT: 3,
    REL_UNRELATED: 9,
}

_code_cache: dict[tuple[str, str], str] = {}

# Local CUI -> {sab: code} index, built from the UMLS release by
# build_code_index.py. When present, code_in reads a concept's source
# code from here instead of calling the UMLS API -- the same code the
# API would return, without the network round trip. relate() calls
# code_in for every source and both concepts, and the neighbor search
# calls relate() against every catalog condition, so serving code_in
# locally is what removes the ~110s hang. A missing index file is fine:
# code_in falls back to the API, unchanged.
_CODE_INDEX_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fda_data", "cui_code_index.json")
_code_index: dict = {}


def _load_code_index() -> None:
    """Seed the local code index from disk. Missing file is fine."""
    if not os.path.exists(_CODE_INDEX_PATH):
        return
    try:
        with open(_CODE_INDEX_PATH, encoding="utf-8") as handle:
            _code_index.update(json.load(handle))
    except Exception:  # noqa: BLE001
        _code_index.clear()


_load_code_index()
_rel_cache: dict[tuple[str, str, str], list[tuple[str, str]]] = {}


def _load_cache() -> None:
    """
    Seed _code_cache and _rel_cache from disk, if the file exists.

    A missing or unreadable cache file is not an error -- it means this
    is the first run, or the cache was deliberately cleared. Either way
    the pipeline degrades to the pre-patch behavior (live calls), not a
    crash.
    """
    if not os.path.exists(_CACHE_PATH):
        return
    try:
        with open(_CACHE_PATH, encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception:  # noqa: BLE001
        return

    for key, value in raw.get("code_cache", {}).items():
        parts = key.split(_KEY_SEP)
        if len(parts) == 2:
            _code_cache[(parts[0], parts[1])] = value

    for key, value in raw.get("rel_cache", {}).items():
        parts = key.split(_KEY_SEP)
        if len(parts) == 3:
            _rel_cache[(parts[0], parts[1], parts[2])] = [
                tuple(pair) for pair in value
            ]


def _save_cache() -> None:
    """
    Write both caches to disk. Called after every new fetch, not only
    at exit -- so a run that fails partway through (network drop,
    Ctrl-C) still keeps whatever it already paid for.
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    payload = {
        "code_cache": {
            _KEY_SEP.join(k): v for k, v in _code_cache.items()
        },
        "rel_cache": {
            _KEY_SEP.join(k): v for k, v in _rel_cache.items()
        },
    }
    tmp_path = _CACHE_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp_path, _CACHE_PATH)
    except Exception:  # noqa: BLE001
        # A failed cache write must never take down a working lookup.
        pass


_load_cache()


def _get(path: str, **params) -> dict:
    params["apiKey"] = cr.UMLS_API_KEY
    url = f"{UMLS}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def code_in(cui: str, sab: str) -> str:
    """The source's own code for this concept, or empty."""
    if not cui or not cr.UMLS_API_KEY:
        return ""
    cached = _code_cache.get((cui, sab))
    if cached is not None:
        return cached

    # Local index first. It carries the same source code the API would
    # return. Only when the index lacks this CUI do we fall through to
    # the live API below.
    if _code_index:
        entry = _code_index.get(cui)
        if entry is not None:
            code = entry.get(sab, "")
            _code_cache[(cui, sab)] = code
            return code
    code = ""
    try:
        atoms = _get(f"/content/current/CUI/{cui}/atoms",
                     sabs=sab, pageSize=5)["result"]
        for atom in atoms:
            raw = atom.get("code", "")
            if raw:
                code = raw.rstrip("/").split("/")[-1]
                break
    except Exception:  # noqa: BLE001
        code = ""

    _code_cache[(cui, sab)] = code
    _save_cache()
    time.sleep(PAUSE)
    return code


def _relatives(sab: str, code: str,
               kind: str) -> list[tuple[str, str]]:
    """parents / children / ancestors of a code, in one source."""
    if not code:
        return []

    # SNOMED is served from the local is-a index when it is loaded --
    # no network, no rate-limit pause. Every other source, and SNOMED
    # itself if the index is absent, falls through to the live API.
    if sab == _SNOMED_SAB and _snomed_index:
        return _snomed_relatives(code, kind)

    # The other sources with a local tree (ICD10CM, NCI, MDR) are served
    # from the hierarchy index when it carries this source. Same shape,
    # no network. A source not in the index falls through to the API.
    if sab in _hierarchy_index:
        return _local_relatives(sab, code, kind)

    cached = _rel_cache.get((sab, code, kind))
    if cached is not None:
        return cached

    result: list[tuple[str, str]] = []
    try:
        payload = _get(f"/content/current/source/{sab}/{code}/{kind}",
                       pageSize=100)["result"]
        result = [(x["ui"], x["name"]) for x in payload]
    except Exception:  # noqa: BLE001
        result = []

    _rel_cache[(sab, code, kind)] = result
    _save_cache()
    time.sleep(PAUSE)
    return result


def _relation_in(sab: str, code_a: str, code_b: str) -> tuple[str, list]:
    """The relation of B to A, according to ONE source."""
    if not code_a or not code_b:
        return REL_NO_HIERARCHY, []

    parents_a = _relatives(sab, code_a, "parents")
    parents_b = _relatives(sab, code_b, "parents")
    ids_a = {u for u, _ in parents_a}
    ids_b = {u for u, _ in parents_b}

    if code_b in ids_a:
        return REL_PARENT, []
    if code_a in ids_b:
        return REL_CHILD, []

    shared = ids_a & ids_b
    if shared:
        names = dict(parents_a + parents_b)
        # DEFINING-ATTRIBUTES GATE (SNOMED only). A sibling is inferred
        # THROUGH a shared parent; it is real only if that parent is a
        # disease family, not a classification axis. A SNOMED parent
        # with >= 1 defining attribute is a clinical entity ("Heart
        # failure"); one with none is a grouper ("Autosomal recessive
        # hereditary disorder"). Keep only DEFINED shared parents. If
        # none survive, the two concepts share only a grouper -- that is
        # a classification axis, not a relationship -- so they are
        # UNRELATED for navigation. Congestive/chronic heart failure
        # share "Heart failure" (defined) and remain SIBLING; Gaucher
        # and cystic fibrosis share only "Autosomal recessive hereditary
        # disorder" (grouper) and are correctly dropped.
        if sab == _SNOMED_SAB and _snomed_defined:
            defined_shared = [s for s in shared
                              if _snomed_defined.get(s)]
            if not defined_shared:
                return REL_UNRELATED, []
            return REL_SIBLING, [names[s]
                                 for s in sorted(defined_shared)]
        return REL_SIBLING, [names[s] for s in sorted(shared)]

    ancestors_a = {u for u, _ in _relatives(sab, code_a, "ancestors")}
    if code_b in ancestors_a:
        return REL_ANCESTOR, []

    ancestors_b = {u for u, _ in _relatives(sab, code_b, "ancestors")}
    if code_a in ancestors_b:
        return REL_DESCENDANT, []

    # Deliberately NOT reported: a shared REMOTE ancestor. Every concept
    # shares the root. Congestive and chronic heart failure share twenty
    # SNOMED ancestors, including "Disorder of thorax." That is not a
    # relationship; it is a statement that both are disorders of the
    # body.
    return REL_UNRELATED, []


def relate(cui_a: str, cui_b: str) -> dict:
    """
    The relation of B to A, asked of every source that has a hierarchy.

    Convergence across independent taxonomies is the confidence, exactly
    as it is for identity. A source that does not carry the concept has
    NOT voted against a relation -- it has not voted, and its silence is
    recorded as NO_HIERARCHY for that source rather than counted as
    disagreement.
    """
    if cui_a and cui_a == cui_b:
        return _result(cui_a, cui_b, REL_EXACT, {}, [])

    by_source: dict[str, dict] = {}
    votes: dict[str, list[str]] = {}

    for name, sab in SOURCES.items():
        code_a = code_in(cui_a, sab)
        code_b = code_in(cui_b, sab)

        if not code_a or not code_b:
            by_source[name] = {"relation": REL_NO_HIERARCHY,
                               "code_a": code_a, "code_b": code_b,
                               "via": []}
            continue

        relation, shared = _relation_in(sab, code_a, code_b)
        # `via` is recorded PER SOURCE, not first-wins.
        #
        # A first version took the first shared parent any source
        # reported, regardless of whether that source won the vote. On
        # NSCLC vs lung cancer it labelled the result "via Lower
        # respiratory tract neoplasms" -- which was MedDRA's SIBLING
        # reasoning, and MedDRA LOST to three sources saying DESCENDANT.
        #
        # A path that belongs to a rejected relation is not the path.
        by_source[name] = {"relation": relation, "code_a": code_a,
                           "code_b": code_b, "via": shared}
        votes.setdefault(relation, []).append(name)

    if not votes:
        return _result(
            cui_a, cui_b, REL_NO_HIERARCHY, by_source, [],
            note=("Neither concept has a taxonomic code in any of the "
                  "six hierarchies. If this is a TRIAL POPULATION -- an "
                  "enrollment definition rather than a disease entity -- "
                  "it has no parent because it is not the kind of thing "
                  "that has one. That is a CATEGORY FACT, not a coverage "
                  "gap."))

    # CONVERGENCE FIRST. Relation rank is only a tiebreak.
    #
    # A first version ranked the relation TYPE above the vote COUNT, and
    # it got NSCLC vs lung cancer wrong: SNOMED, MeSH, and NCIt all said
    # DESCENDANT, MedDRA alone said SIBLING, and the rule picked
    # SIBLING -- because SIBLING outranked DESCENDANT in the table.
    #
    # That inverts the principle used everywhere else in this project:
    # agreement across independent authorities IS the confidence. Three
    # taxonomies agreeing beats one, regardless of which relation is
    # "closer" in some ordering I invented.
    #
    # MedDRA calls them siblings because its five-level regulatory
    # hierarchy is coarser than a clinical taxonomy. That is a carving
    # difference, and it is recorded as dissent -- not allowed to
    # overrule three sources.
    #
    # UNRELATED still loses to any structural relation: a source that
    # finds no path has not asserted that none exists.
    def rank(relation: str) -> tuple:
        structural = 1 if relation == REL_UNRELATED else 0
        return (structural, -len(votes[relation]),
                _RANK.get(relation, 9))

    winner = min(votes, key=rank)

    # the shared parent, from the sources that AGREED on the winner
    via: list[str] = []
    for name in votes[winner]:
        shared = by_source[name].get("via") or []
        for parent in shared:
            if parent not in via:
                via.append(parent)

    return _result(cui_a, cui_b, winner, by_source,
                   sorted(votes[winner]), via=via,
                   dissent={r: v for r, v in votes.items()
                            if r != winner})


def _result(cui_a, cui_b, relation, by_source, agreeing,
            **kwargs) -> dict:
    return {
        "cui_a": cui_a,
        "cui_b": cui_b,
        "relation": relation,
        "agreeing_sources": agreeing,
        "n_agreeing": len(agreeing),
        "by_source": by_source,
        "via": kwargs.get("via", []),
        "dissent": kwargs.get("dissent", {}),
        "note": kwargs.get("note", ""),
    }


def neighbors(cui: str, sab: str = "SNOMEDCT_US") -> dict:
    """
    The immediate structural neighborhood of a concept, from one source.

    This is what a developer needs when nothing exists for their exact
    condition: here is what is nearby, and here is how it relates.

    It is NAVIGATION. This tool has no opinion about whether any of it
    applies to their trial -- that is a regulatory judgment, and the
    instrument's qualified context of use is where it is answered.
    """
    code = code_in(cui, sab)
    if not code:
        return {"cui": cui, "source": sab, "code": "",
                "hierarchy_available": False,
                "parents": [], "children": [], "siblings": []}

    parents = _relatives(sab, code, "parents")
    children = _relatives(sab, code, "children")

    siblings: list[tuple[str, str]] = []
    seen = {code}
    for parent_id, _name in parents:
        for sib_id, sib_name in _relatives(sab, parent_id, "children"):
            if sib_id not in seen:
                seen.add(sib_id)
                siblings.append((sib_id, sib_name))

    return {
        "cui": cui,
        "source": sab,
        "code": code,
        "hierarchy_available": True,
        "parents": parents,
        "children": children,
        "siblings": sorted(siblings, key=lambda s: s[1]),
    }


def main() -> None:
    if not cr.UMLS_API_KEY:
        print("ERROR: no UMLS_API_KEY in .env")
        return

    if len(sys.argv) == 3:
        result = relate(sys.argv[1], sys.argv[2])
        print()
        print(f'  {result["cui_a"]}  ->  {result["cui_b"]}')
        print(f'  RELATION : {result["relation"]}')
        print(f'  agreed by: {result["n_agreeing"]} sources '
              f'{result["agreeing_sources"]}')
        if result["via"]:
            print(f'  via      : {result["via"]}')
        if result["dissent"]:
            print(f'  dissent  : {result["dissent"]}')
        if result["note"]:
            print(f'  NOTE     : {result["note"]}')
        print()
        print('  per source:')
        for name, detail in result["by_source"].items():
            print(f'      {name:<8} {detail["relation"]:<14} '
                  f'{detail["code_a"] or "-":<12} '
                  f'{detail["code_b"] or "-"}')
        print()
        return

    if len(sys.argv) == 2:
        hood = neighbors(sys.argv[1])
        print()
        print(f'  CUI {hood["cui"]}  {hood["source"]} {hood["code"]}')
        if not hood["hierarchy_available"]:
            print('  NO_HIERARCHY -- this concept has no taxonomic code')
            print('  in this source. If it is a trial population, it')
            print('  has no parent ANYWHERE, because it is not the kind')
            print('  of thing that has one.')
            print()
            return
        for label, key in (("parents", "parents"),
                           ("children", "children"),
                           ("siblings", "siblings")):
            entries = hood[key]
            print(f'  {label} ({len(entries)}):')
            for _code, name in entries[:12]:
                print(f'      {name}')
        print()
        return

    print("usage:")
    print('  python3 hierarchy_matcher.py CUI          # neighborhood')
    print('  python3 hierarchy_matcher.py CUI_A CUI_B  # relation')


if __name__ == "__main__":
    main()