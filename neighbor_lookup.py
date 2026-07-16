"""
neighbor_lookup.py
------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

SPEC section 4.

Runs only when coa_lookup found no COA for the user's condition. It
answers: FDA has nothing for this disease -- does it have something for
a structurally related one, and how is it related?

THE CANONICAL-OBJECT PRINCIPLE. Every catalog condition was resolved
once, at catalog build, into a sealed identity (a CUI). The user's
disease was resolved once, in Step 1. This tool compares a sealed CUI
against the catalog's sealed CUIs, by calling hierarchy_matcher.relate
for each pair. It never reads a neighbor's NAME and never calls
condition_resolver -- identity is a settled upstream concern, and a
downstream step that re-solves it is the anti-pattern this architecture
exists to avoid.

WHAT IT DOES NOT DO. It does not attach COAs (that is
neighbor_coa_lookup). It does not say an instrument applies (a
regulatory judgment, FDA's). It does not stop the run when a source
errors -- it records that source as degraded, for calibration, and
continues with the sources that answered.

WHERE THE SIBLING GATE LIVES. The judgment that a shared-parent sibling
is a real disease-family relation rather than a classification-axis
artifact (Gaucher/CF sharing only "autosomal recessive disorder") is
made in hierarchy_matcher, by the defining-attributes gate -- because
it is a fact about the ontology, not about navigation. By the time a
relation reaches this tool, a grouper-only sibling has already been
resolved to UNRELATED and will not appear. This tool surfaces what
relate() returns.

THREE COMPLETED-CHECK OUTCOMES, plus per-source degradation:
  NEIGHBORS_FOUND        one or more catalog conditions relate
  NO_NEIGHBOR_IN_CATALOG has a CUI, search completed, none related
                         (a verified absence -- checked, found none)
  NO_HIERARCHY           no CUI to relate from (a category fact: a
                         trial population or guidance construct is not
                         the kind of thing that has a taxonomic parent)
And separately, degraded_sources[] records any of the six sources whose
lookup ERRORED during the search -- distinct from a source that
answered "no relation." A degraded source is a calibration signal, not
a content answer, and never a blank.
"""

import hierarchy_matcher as hm

STATUS_NEIGHBORS_FOUND = "NEIGHBORS_FOUND"
STATUS_NO_NEIGHBOR = "NO_NEIGHBOR_IN_CATALOG"
STATUS_NO_HIERARCHY = "NO_HIERARCHY"

# The relations that count as a structural neighbor worth surfacing.
# EXACT is excluded on purpose: if the user's own CUI were in the
# catalog, coa_lookup would have found its COA and this tool would not
# be running. UNRELATED and NO_HIERARCHY are not neighbors.
_STRUCTURAL = frozenset({
    hm.REL_PARENT,
    hm.REL_CHILD,
    hm.REL_SIBLING,
    hm.REL_ANCESTOR,
    hm.REL_DESCENDANT,
})

_NO_CUI_NOTE = (
    "The condition has no CUI: no vocabulary carries it (a trial "
    "population or a guidance-defined construct). It cannot be related "
    "to catalog conditions because it is not the kind of thing that "
    "has a taxonomic parent. This is a category fact, not a coverage "
    "gap."
)

_NONE_NOTE = (
    "Checked every catalog condition across the hierarchy sources; "
    "none is structurally related to this condition. FDA has no COA "
    "for this disease or for any related condition in the catalog."
)


def find_neighbors(condition: dict, catalog: dict) -> dict:
    """
    Find the catalog conditions structurally related to a sealed
    condition object.

    Args:
        condition: the sealed condition object from condition_resolver.
            Its "cui" is the identity we relate FROM. If it has no CUI,
            there is nothing to relate and the result is NO_HIERARCHY.
        catalog: the loaded COA catalog. Its "by_cui" maps each
            catalog condition's sealed CUI to its entry/entries; those
            CUIs are what we relate AGAINST. No names are used.

    Returns:
        A sealed result (see module docstring for the status set).
        neighbors[] carries, per related catalog condition, its name,
        its CUI, the converged relation, and the sources that agreed.
        degraded_sources[] carries any source that ERRORED during the
        search, for calibration.
    """
    user_cui = (condition or {}).get("cui") or ""
    by_cui = (catalog or {}).get("by_cui", {}) or {}

    if not user_cui:
        return {
            "status": STATUS_NO_HIERARCHY,
            "cui": "",
            "neighbors": [],
            "note": _NO_CUI_NOTE,
            "degraded_sources": [],
        }

    neighbors: list[dict] = []
    degraded: set[str] = set()

    for catalog_cui, entries in by_cui.items():
        if not catalog_cui or catalog_cui == user_cui:
            # No self-relation: were it the same CUI, coa_lookup would
            # have found the COA and this tool would not be running.
            continue
        try:
            result = hm.relate(user_cui, catalog_cui)
        except Exception:  # noqa: BLE001
            # A source (or the relate call) ERRORED. This is a
            # degradation, not a content answer. Record it for
            # calibration and continue; do not let it read as
            # "no relation," and do not stop the run.
            degraded.add(catalog_cui)
            continue

        relation = result.get("relation", "")
        if relation not in _STRUCTURAL:
            continue

        # The catalog condition's display name: taken from the sealed
        # catalog entry, NOT re-resolved. entries is a list; the label
        # is identical across entries for one CUI, so the first serves.
        label = ""
        if entries:
            first = entries[0] or {}
            label = first.get("label") or first.get("condition") or ""

        neighbors.append({
            "condition": label,
            "cui": catalog_cui,
            "relation": relation,
            "agreeing_sources": result.get("agreeing_sources", []),
        })

    degraded_sources = sorted(degraded)

    if neighbors:
        status = STATUS_NEIGHBORS_FOUND
        note = ""
    else:
        status = STATUS_NO_NEIGHBOR
        note = _NONE_NOTE

    # Stable order: strongest agreement first, then by name, so the
    # output is deterministic regardless of dict iteration order.
    neighbors.sort(
        key=lambda n: (-len(n["agreeing_sources"]), n["condition"]))

    return {
        "status": status,
        "cui": user_cui,
        "neighbors": neighbors,
        "note": note,
        "degraded_sources": degraded_sources,
    }