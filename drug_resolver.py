"""
drug_resolver.py
----------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Resolve a free-text intervention string to a canonical drug identity.

WHY THIS EXISTS

ClinicalTrials.gov intervention names are free text. One drug appears
under many strings: "Dapagliflozin", "Dapagliflozin 10mg Tab",
"Dapagliflozin (Forxiga)", "dapagliflozine" are one drug written nine
ways. Counting the raw strings overcounts, and it is the exact
synonym-list trap this project rejects for diseases: a string is not an
identity.

So intervention strings are RESOLVED to a canonical drug the same way a
disease name is resolved to a CUI -- here the canonical key is the
RxNorm INGREDIENT rxcui. All nine dapagliflozin strings resolve to one
ingredient rxcui and are counted once.

A string that does not resolve to a drug ingredient -- "placebo",
"standard of care", "GDMT", "monotherapy", "blank control" -- returns
UNRESOLVED. It is not a drug, so it falls out because it is not the kind
of thing this resolves, NOT because a phrase was blacklisted. That
replaces substring control-filtering with a principled test.

A string that IS a drug but is not in RxNorm -- an investigational code
like "AZD4831" or "HRS-1893", too new to be coded -- returns UNRESOLVED
with reason NOT_IN_RXNORM, and the caller KEEPS it, labeled, rather than
dropping it. "We could not resolve this" and "this is not a drug" are
different facts, and a real experimental drug must not be silently lost.

RxNav is a live NLM API, no key required. Same access pattern as
download_rxnorm_indications.py: pause between calls, cache to disk.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
CACHE_PATH = os.path.join(DATA_DIR, "drug_resolve_cache.json")

RXNAV = "https://rxnav.nlm.nih.gov/REST"
PAUSE = 0.25
TIMEOUT = 30

STATUS_RESOLVED = "RESOLVED"
STATUS_UNRESOLVED_NOT_DRUG = "UNRESOLVED_NOT_A_DRUG"
STATUS_NOT_IN_RXNORM = "UNRESOLVED_NOT_IN_RXNORM"

# Obvious non-drug intervention strings. This is NOT the control filter
# -- resolution handles controls by failing to resolve them. This is a
# short-circuit so we do not waste API calls on strings that plainly
# name no drug. Anything not caught here still gets a real resolution
# attempt; nothing is dropped on the basis of this list alone.
_OBVIOUS_NON_DRUG = re.compile(
    r"^\s*(placebo|sham|no intervention|observation|blank control|"
    r"control|standard[\s\-]|usual care|best supportive care|"
    r"supportive care|monotherapy|combination therapy|polypill|"
    r"medication management|weight loss|medical (therapy|treatment)|"
    r"optimal medical|optimized medical|guideline[\s\-]directed|gdmt|"
    r"vehicle|saline|sodium chloride|iv solution|iv fluids?)\b",
    re.IGNORECASE)

_cache: dict = {}


def _load_cache() -> None:
    if not os.path.exists(CACHE_PATH):
        return
    try:
        with open(CACHE_PATH, encoding="utf-8") as handle:
            _cache.update(json.load(handle))
    except Exception:  # noqa: BLE001
        _cache.clear()


def _save_cache() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_cache, handle)
        os.replace(tmp, CACHE_PATH)
    except Exception:  # noqa: BLE001
        pass


_load_cache()


def _get(path: str, **params) -> dict:
    url = f"{RXNAV}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "fda-recon/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def _clean(name: str) -> str:
    """
    Strip dose, form, and bracket noise so the match lands on the drug,
    not the packaging. "Dapagliflozin 10mg Tab [Forxiga]" -> a stem the
    approximate matcher can resolve. Conservative: it removes obvious
    dose/form tokens, not chemistry.
    """
    s = name
    s = re.sub(r"\[[^\]]*\]", " ", s)          # [Brand]
    s = re.sub(r"\([^)]*\)", " ", s)           # (parenthetical)
    # dose amounts: 10 mg, 200mg, 5-10 mg, 0.9%
    s = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|g|ml|%|units?|iu)\b", " ",
               s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|g|ml)\s*/\s*"
               r"\d+(\.\d+)?\s*(mg|mcg|g|ml)\b", " ", s,
               flags=re.IGNORECASE)
    # form words
    s = re.sub(r"\b(oral|tablet|tablets|tab|tabs|capsule|capsules|"
               r"cap|caps|injection|injectable|solution|extended[\s\-]"
               r"release|sustained[\s\-]release|enteric[\s\-]coated|"
               r"bid|tid|qd|daily|product|group|dose|high|low|medium)\b",
               " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" -,/")
    return s


def _ingredients_of(rxcui: str) -> list[tuple[str, str]]:
    """
    ALL ingredient (rxcui, name) pairs for a concept, via RxNav related.

    A single drug returns one. A COMBINATION returns several --
    sacubitril/valsartan returns both sacubitril and valsartan -- and
    all are kept, so the combination is represented by its full
    ingredient set, not silently reduced to one half.
    """
    out: list[tuple[str, str]] = []
    try:
        data = _get(f"/rxcui/{rxcui}/related.json", tty="IN")
        time.sleep(PAUSE)
        groups = (data.get("relatedGroup", {})
                  .get("conceptGroup", []) or [])
        for g in groups:
            if g.get("tty") == "IN":
                for p in g.get("conceptProperties", []) or []:
                    rc = p.get("rxcui", "")
                    nm = p.get("name", "")
                    if rc and nm:
                        out.append((rc, nm))
    except Exception:  # noqa: BLE001
        pass
    return out


def ingredient_rxcuis_of(rxcui: str) -> list:
    """
    The ingredient rxcui(s) for a given rxcui, cached. If the concept
    has no IN ingredient (already an ingredient, or a class), the rxcui
    itself is returned. Used to normalize a set of drug rxcuis to
    ingredient level -- e.g. building the approved-drug set.
    """
    if not rxcui:
        return []
    key = f"ING:{rxcui}"
    hit = _cache.get(key)
    if hit is not None:
        return list(hit)
    pairs = _ingredients_of(rxcui)
    ids = [rc for rc, _n in pairs] or [rxcui]
    _cache[key] = ids
    _save_cache()
    return list(ids)


def _rxcui_for_name(name: str) -> str:
    """Exact/normalized name -> rxcui, or empty."""
    try:
        data = _get("/rxcui.json", name=name, search="2")
        time.sleep(PAUSE)
        ids = (data.get("idGroup", {}).get("rxnormId", []) or [])
        return ids[0] if ids else ""
    except Exception:  # noqa: BLE001
        return ""


def _approx_rxcui(name: str) -> str:
    """Fuzzy match a messy string -> best candidate rxcui, or empty."""
    try:
        data = _get("/approximateTerm.json", term=name, maxEntries="1")
        time.sleep(PAUSE)
        cands = (data.get("approximateGroup", {})
                 .get("candidate", []) or [])
        if cands:
            return cands[0].get("rxcui", "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def resolve(intervention: str) -> dict:
    """
    Resolve an intervention string to a canonical drug ingredient.

    Returns:
        {status, query, ingredient_rxcui, ingredient} -- ingredient
        fields empty unless status is RESOLVED.
    """
    query = (intervention or "").strip()
    if not query:
        return {"status": STATUS_UNRESOLVED_NOT_DRUG, "query": query,
                "ingredient_rxcui": "", "ingredient": ""}

    hit = _cache.get(query)
    if hit is not None:
        return dict(hit)

    if _OBVIOUS_NON_DRUG.match(query):
        result = {"status": STATUS_UNRESOLVED_NOT_DRUG, "query": query,
                  "ingredient_rxcui": "", "ingredient": ""}
        _cache[query] = result
        _save_cache()
        return dict(result)

    # Try the raw name, then a cleaned form, then approximate match.
    rxcui = _rxcui_for_name(query)
    if not rxcui:
        cleaned = _clean(query)
        if cleaned and cleaned.lower() != query.lower():
            rxcui = _rxcui_for_name(cleaned)
        if not rxcui and cleaned:
            rxcui = _approx_rxcui(cleaned)
    if not rxcui:
        # A development-code string often names the real drug in
        # parentheses: "LCZ696 (sacubitril/valsartan)". Try the
        # parenthetical content before giving up.
        paren = re.search(r"\(([^)]+)\)", query)
        if paren:
            inner = paren.group(1).strip()
            if inner and not _OBVIOUS_NON_DRUG.match(inner):
                rxcui = _rxcui_for_name(inner) or _approx_rxcui(inner)
    if not rxcui:
        # A drug string RxNorm does not carry (investigational code).
        # Keep it, labeled, rather than dropping it.
        result = {"status": STATUS_NOT_IN_RXNORM, "query": query,
                  "ingredient_rxcui": "", "ingredient": ""}
        _cache[query] = result
        _save_cache()
        return dict(result)

    ingredients = _ingredients_of(rxcui)
    if not ingredients:
        # rxcui resolved but has no IN ingredient (already an
        # ingredient, or a class). Use the rxcui itself as canonical.
        ingredients = [(rxcui, query)]

    # Sort by ingredient name so a combination gets ONE canonical
    # identity regardless of the order the API returns, and regardless
    # of how the source string wrote it ("sacubitril/valsartan" and
    # "valsartan-sacubitril" resolve to the same key).
    ingredients.sort(key=lambda p: p[1].lower())
    names = [n for _rc, n in ingredients]
    rxcuis = [rc for rc, _n in ingredients]
    ing_name = "/".join(names)
    ing_rxcui = "/".join(rxcuis)

    result = {"status": STATUS_RESOLVED, "query": query,
              "ingredient_rxcui": ing_rxcui, "ingredient": ing_name}
    _cache[query] = result
    _save_cache()
    return dict(result)