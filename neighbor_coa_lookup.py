"""
neighbor_coa_lookup.py
----------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

SPEC section 5.

Takes the sealed neighbor result from neighbor_lookup and attaches each
neighbor's COAs, read verbatim from the catalog. Finding a related
condition and attaching its COAs are two jobs, kept in two tools, so a
failure in one is diagnosable without reading the other.

WHAT IT DOES NOT DO. It does not re-compute the relation (already
sealed by neighbor_lookup). It does not say an instrument applies, or
judge fit -- that is a regulatory judgment, FDA's. It does not drop a
neighbor that has no COA: that neighbor is kept with coas == [], a
stated empty rather than a silent drop, because "a sibling exists and
it too has no COA" is a verified fact about the neighborhood. What to
DISPLAY of a COA-less neighbor is a presentation concern, not this
tool's -- the tool reports completely.
"""

STATUS_ATTACHED = "ATTACHED"
STATUS_NOTHING = "NOTHING_TO_ATTACH"

# The COA fields carried verbatim from the catalog. The catalog's COA
# entries are the authority; nothing here is summarized or re-derived.
_COA_FIELDS = (
    "instrument",
    "concept",
    "context_of_use",
    "coa_type",
    "stage",
    "qualified",
)


def attach_coas(neighbor_result: dict, catalog: dict) -> dict:
    """
    Attach each neighbor's COAs, verbatim from the catalog.

    Args:
        neighbor_result: the sealed output of neighbor_lookup. Its
            "neighbors" list carries each related catalog condition with
            its CUI and relation. The relation and CUI pass through
            unchanged.
        catalog: the loaded COA catalog. Its "by_cui" maps a catalog
            CUI to its entry/entries, each of which holds that
            condition's COAs.

    Returns:
        A sealed result. Each neighbor from the input is returned
        unchanged plus a "coas" list -- possibly empty. status is
        ATTACHED when there was at least one neighbor to process,
        NOTHING_TO_ATTACH when the input carried no neighbors.
    """
    neighbors_in = (neighbor_result or {}).get("neighbors", []) or []
    by_cui = (catalog or {}).get("by_cui", {}) or {}

    if not neighbors_in:
        return {"status": STATUS_NOTHING, "neighbors": []}

    neighbors_out: list[dict] = []
    for neighbor in neighbors_in:
        cui = neighbor.get("cui", "")
        coas = _coas_for(by_cui.get(cui, []))
        # Pass the neighbor through unchanged; add coas (possibly []).
        enriched = dict(neighbor)
        enriched["coas"] = coas
        neighbors_out.append(enriched)

    return {"status": STATUS_ATTACHED, "neighbors": neighbors_out}


def _coas_for(entries: list) -> list[dict]:
    """
    The COAs a catalog CUI carries, verbatim. entries is the catalog's
    list for one CUI; each entry holds a "coas" list. A CUI with no COAs
    yields [] -- a stated empty, kept by the caller, never dropped.
    """
    out: list[dict] = []
    for entry in entries or []:
        for coa in (entry or {}).get("coas", []) or []:
            out.append({field: coa.get(field) for field in _COA_FIELDS})
    return out