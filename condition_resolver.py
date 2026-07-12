"""
condition_resolver.py
---------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Resolves a disease NAME to a canonical condition object.

This is the ONE place identity happens. Nothing downstream re-derives
what disease a string refers to. The COA lookup, the drug lookup, and
the hierarchy matcher all receive a sealed resolved-condition object
and do their one job against it. The resolver does not look at the COA
catalog, does not look at drugs, and does not walk the hierarchy to
find related entries -- those are other tools.

WHY FOUR SOURCES

There is no single authority for disease identity. This is not a
rare-disease quirk; it is true everywhere. The vocabularies do not
merely disagree -- they CARVE THE SPACE DIFFERENTLY, because they were
built to answer different questions:

  MONDO    models disease IDENTITY for research. It is the canonical
           anchor and the only source with a usable hierarchy.
  MeSH     indexes TERMS for literature retrieval. Its entry terms are
           the alternate names authors actually use.
  SNOMED   records CLINICAL language -- what a clinician writes in a
           chart. FDA's COA condition strings were written by clinical
           scientists, so they land here and not in the research
           ontologies.
  ICD-10   is a BILLING taxonomy. Included last, and provisionally.

Confirmed on FDA's own COA catalog: "Chronic Heart Failure" -- FDA's
own string -- exists in NEITHER MONDO NOR MeSH. SNOMED has it as a
first-class concept (48447003). One source is not enough.

WHY CONVERGENCE, NOT A FALLBACK CHAIN

The resolver does not stop at the first source that fires. It asks ALL
of them and looks at where they AGREE. Agreement across independent
authorities -- built for different purposes, by different bodies -- is
corroboration in exactly the sense a two-citation minimum is
corroboration. A lone source is weaker evidence than four, and the
object carries that distinction rather than flattening it into a score.

  HIGH_CONFIDENCE      >= 3 sources exactly matched the query
  MODERATE_CONFIDENCE  2 sources matched
  LOW_CONFIDENCE       exactly 1 source matched; it stands alone
  CONFLICT_DETECTED    sources that CAN be compared (via MONDO xref)
                       point at DIFFERENT MONDO classes
  UNRESOLVED           nothing matched

MONDO IS A PEER, NOT A GATEKEEPER

An earlier version required a MONDO cross-reference before a source's
hit could count. That was wrong, and the corpus proved it within five
queries:

  Sarcopenia   -- MeSH (D055948), SNOMED (772791006), and ICD-10
                  (M62.84) ALL matched exactly. MONDO carries no xref
                  to any of them. The resolver returned UNRESOLVED.
                  Three independent authorities agreed and the answer
                  was thrown away because a FOURTH had a coverage gap.

  Chronic heart failure -- SNOMED has it as a first-class concept
                  (48447003). Discarded for the same reason.

  Alzheimer's disease -- SNOMED returned the exact concept (26929004)
                  and it was discarded, even though MONDO and MeSH had
                  already resolved the disease.

A missing MONDO xref is a fact about MONDO. It is not a fact about the
disease. The gene resolver never required a MONDO ID to resolve a gene
-- it chained Orphanet, OMIM, HGNC, and ClinGen, and MONDO was one
input among several. The same holds here.

So: convergence is counted over EXACT STRING MATCHES, each source
independently confirming that the query names a disease in its
vocabulary. MONDO supplies the canonical ID and the hierarchy WHEN IT
CAN; when it cannot, the resolution still stands, anchored to the
highest-priority source that did resolve, with hierarchy_available set
false so no downstream tool assumes a hierarchy it does not have.

  canonical anchor  MONDO if available, else SNOMED, else MeSH, else
                    ICD-10
  hierarchy_available  True only when MONDO anchored it -- MONDO is the
                    only source here carrying a usable is_a hierarchy

CONFLICT is only detectable BETWEEN COMPARABLE IDENTIFIERS. Two sources
that both bridge to MONDO and disagree about WHICH class is a real
conflict, and it is surfaced. Two sources with no common identifier
cannot be said to disagree; they can only both have matched the string.

The gene resolver takes its confidence from ClinGen -- an external
authority that publishes its own curated gene-disease validity
classification. Condition resolution has no ClinGen. No body publishes
"this string-to-disease mapping is Definitive." So cross-source
agreement is not a substitute for evidence; it is the ONLY evidence
this domain offers, and it is the same epistemics: corroboration from
outside, never self-assertion.

The sources are never blended. The object records WHICH source said
WHAT. A rate that mixed them would be a number no auditor could walk
back down to its cause.

EXACT MATCH ONLY -- AND WHY

Every source is queried for an EXACT normalized string match. No
ranked hits, no fuzzy scoring, no "closest" candidate.

This is not caution for its own sake. SNOMED's search for "breast
cancer" returns, ranked:

    254837009  Malignant neoplasm of breast        <- correct
    429740004  Family history of breast cancer     <- a finding about
                                                      a RELATIVE, not
                                                      the disease

Both are legitimate SNOMED concepts. A resolver that accepted a ranked
top hit would eventually accept the second one for some query, and the
result would be PLAUSIBLE, CONFIDENT, AND WRONG -- the failure mode
that no reviewer catches, because nothing about the output looks
broken. The false-positive risk is not a property of SNOMED. It is a
property of RANKING. Removing ranking removes it.

Exactness costs reach. That cost is measured, not assumed -- see the
near-miss log below.

THE NEAR-MISS LOG IS A CALIBRATION INSTRUMENT

Every case where a source WOULD have resolved under a looser rule is
recorded: the source, the query, the candidate it would have returned,
and why the strict rule refused it. This is not debugging output. It is
the instrument that lets the strict rule be evaluated with evidence
instead of instinct.

After a run against the full FDA corpus (54 COA conditions, 199
Compendium diseases), the near-miss log answers the only question that
matters: were the refusals CORRECT (family-history traps) or were they
GOOD RESCUES the strict rule wrongly discarded? Only then should the
rule be loosened, and only in the specific way the evidence supports.

RED IS HEALTHY. A refusal is the system working. UNRESOLVED on a string
that exists in no controlled vocabulary is the correct answer, and it
is a FINDING -- it means FDA wrote a condition name that no authority
carries.

ICD-10 IS AN OPEN EXPERIMENT

It is queried and recorded, but its marginal contribution is the point:
run the corpus with MONDO + MeSH + SNOMED, then again with ICD-10, and
compare. If it rescues cases nothing else could, it stays. If it
rescues nothing -- or worse, if it returns SUBTYPES for parent queries,
which its billing-oriented structure makes likely -- it is dropped with
evidence rather than on instinct.

INPUTS (all built by their own scripts, all on disk)
  fda_data/mondo_resolution_index.csv
  fda_data/mesh_disease_index.csv
  fda_data/icd10cm_index.csv
  SNOMED via the UMLS REST API (UMLS_API_KEY in .env)
"""

import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")

MONDO_INDEX = os.path.join(DATA_DIR, "mondo_resolution_index.csv")
MESH_INDEX = os.path.join(DATA_DIR, "mesh_disease_index.csv")
ICD10_INDEX = os.path.join(DATA_DIR, "icd10cm_index.csv")

UMLS_SEARCH_URL = "https://uts-ws.nlm.nih.gov/rest/search/current"
UMLS_TIMEOUT_SECONDS = 30

SOURCE_MONDO = "mondo"
SOURCE_MESH = "mesh"
SOURCE_SNOMED = "snomed"
SOURCE_ICD10 = "icd10"

STATUS_HIGH = "HIGH_CONFIDENCE"
STATUS_MODERATE = "MODERATE_CONFIDENCE"
STATUS_LOW = "LOW_CONFIDENCE"
STATUS_CONFLICT = "CONFLICT_DETECTED"
STATUS_UNRESOLVED = "UNRESOLVED"

_PAREN_RE = re.compile(r"\s*\([^)]*\)")
_PUNCT_RE = re.compile(r"[^a-z0-9\s\-']")
_SPACE_RE = re.compile(r"\s+")


def _api_key() -> str:
    """Read UMLS_API_KEY from .env without dotenv's path guessing."""
    env_path = Path(_BASE_DIR) / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("UMLS_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


UMLS_API_KEY = _api_key()


def normalize(name: str) -> str:
    """
    Deterministic normalization, applied identically to every source.

    Drops FDA's embedded parenthetical abbreviation ("Chronic Kidney
    Disease (CKD)" -> "chronic kidney disease"), lowercases, and strips
    punctuation EXCEPT apostrophes and hyphens.

    The apostrophe exemption is not cosmetic. An earlier version
    stripped it, which turned "Alzheimer's Disease" into
    "alzheimer s disease" and made four of the most recognizable
    diseases in medicine unresolvable. Most of what looks like a
    vocabulary gap is a normalization bug.
    """
    if not name:
        return ""
    text = _PAREN_RE.sub(" ", name)
    text = text.replace("\u2019", "'")
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _load_mondo() -> tuple[dict, dict, dict]:
    """
    Returns (term -> mondo_id, mondo_id -> record, xrefs).

    xrefs maps ('mesh', 'D006333') -> mondo_id, and likewise for
    ('snomed', '48447003') and ('icd10', 'I50.9'), so a hit in another
    vocabulary can be brought back to the canonical anchor.
    """
    terms: dict[str, str] = {}
    records: dict[str, dict] = {}
    xrefs: dict[tuple[str, str], str] = {}

    with open(MONDO_INDEX, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mondo_id = row["mondo_id"]
            records[mondo_id] = {
                "mondo_id": mondo_id,
                "label": row["label"],
                "parents": [
                    p for p in row["parents"].split("|") if p],
                "definition": row["definition"],
            }
            for term in [row["label"]] + row["exact_synonyms"].split("|"):
                key = normalize(term)
                if key:
                    terms.setdefault(key, mondo_id)
            for code in row["xref_mesh"].split("|"):
                if code:
                    xrefs.setdefault((SOURCE_MESH, code), mondo_id)
            for code in row["xref_sctid"].split("|"):
                if code:
                    xrefs.setdefault((SOURCE_SNOMED, code), mondo_id)
            for code in row["xref_icd10cm"].split("|"):
                if code:
                    xrefs.setdefault((SOURCE_ICD10, code), mondo_id)

    return terms, records, xrefs


def _load_mesh() -> dict:
    """term -> mesh_id, over labels and every entry term."""
    terms: dict[str, str] = {}
    with open(MESH_INDEX, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mesh_id = row["mesh_id"]
            candidates = [row["name"]] + row["entry_terms"].split("|")
            for term in candidates:
                key = normalize(term)
                if key:
                    terms.setdefault(key, mesh_id)
    return terms


def _load_icd10() -> dict:
    """term -> dotted ICD-10-CM code."""
    terms: dict[str, str] = {}
    with open(ICD10_INDEX, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = normalize(row["name"])
            if key:
                terms.setdefault(key, row["code_dotted"])
    return terms


def _snomed_lookup(query: str) -> tuple[list[dict], list[dict]]:
    """
    Query SNOMED. Returns (exact_hits, near_misses).

    SNOMED is a RANKED search, not a lookup. Only concepts whose name
    normalizes to the query string are accepted. Everything else is
    recorded as a near miss -- never silently used.
    """
    if not UMLS_API_KEY:
        return [], [{
            "source": SOURCE_SNOMED,
            "reason": "NO_API_KEY",
            "candidate": "",
        }]

    params = urllib.parse.urlencode({
        "string": query,
        "sabs": "SNOMEDCT_US",
        "returnIdType": "code",
        "apiKey": UMLS_API_KEY,
        "pageSize": 10,
    })
    request = urllib.request.Request(
        f"{UMLS_SEARCH_URL}?{params}",
        headers={"User-Agent": "fda-recon/1.0",
                 "Accept": "application/json"})

    try:
        with urllib.request.urlopen(
                request, timeout=UMLS_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        return [], [{"source": SOURCE_SNOMED,
                     "reason": f"HTTP_{exc.code}", "candidate": ""}]
    except Exception as exc:  # noqa: BLE001
        return [], [{"source": SOURCE_SNOMED,
                     "reason": f"ERROR:{type(exc).__name__}",
                     "candidate": ""}]

    exact = []
    near = []
    target = normalize(query)
    for result in payload.get("result", {}).get("results", []):
        code = result.get("ui", "")
        name = result.get("name", "")
        if not code or code == "NONE":
            continue
        if normalize(name) == target:
            exact.append({"code": code, "name": name})
        else:
            near.append({
                "source": SOURCE_SNOMED,
                "reason": "RANKED_NOT_EXACT",
                "candidate": f"{code} {name}",
            })
    return exact, near


def resolve(
    name: str,
    mondo_terms: dict,
    mondo_records: dict,
    mondo_xrefs: dict,
    mesh_terms: dict,
    icd10_terms: dict,
    use_icd10: bool = True,
    use_snomed: bool = True,
) -> dict:
    """
    Resolve one disease name against all sources. Returns a sealed
    canonical condition object. Never re-derives, never blends.
    """
    query = normalize(name)
    hits: dict[str, dict] = {}
    near_misses: list[dict] = []

    if not query:
        return {
            "query": name,
            "normalized": "",
            "status": STATUS_UNRESOLVED,
            "anchor": "",
            "mondo_id": "",
            "hierarchy_available": False,
            "label": "",
            "parents": [],
            "resolved_by": [],
            "source_hits": {},
            "candidates": [],
            "near_misses": [{"source": "normalizer",
                             "reason": "EMPTY_AFTER_NORMALIZATION",
                             "candidate": name}],
        }

    # --- MONDO: direct
    mondo_id = mondo_terms.get(query)
    if mondo_id:
        hits[SOURCE_MONDO] = {"code": mondo_id, "mondo_id": mondo_id}

    # --- MeSH: term hit, then bridge to MONDO via xref
    mesh_id = mesh_terms.get(query)
    if mesh_id:
        # a missing xref is a property of the resolution, not a refusal
        hits[SOURCE_MESH] = {
            "code": mesh_id,
            "mondo_id": mondo_xrefs.get((SOURCE_MESH, mesh_id), ""),
        }

    # --- SNOMED: exact only
    if use_snomed:
        exact, near = _snomed_lookup(query)
        near_misses.extend(near)
        # prefer an exact hit that also bridges to MONDO; if none
        # bridges, still take the first exact hit -- SNOMED matching
        # the string exactly IS a resolution.
        for candidate in exact:
            bridged = mondo_xrefs.get(
                (SOURCE_SNOMED, candidate["code"]), "")
            if bridged:
                hits[SOURCE_SNOMED] = {
                    "code": candidate["code"], "mondo_id": bridged}
                break
        else:
            if exact:
                hits[SOURCE_SNOMED] = {
                    "code": exact[0]["code"], "mondo_id": ""}

    # --- ICD-10: exact only, and provisional
    if use_icd10:
        icd_code = icd10_terms.get(query)
        if icd_code:
            hits[SOURCE_ICD10] = {
                "code": icd_code,
                "mondo_id": mondo_xrefs.get((SOURCE_ICD10, icd_code), ""),
            }

    # --- convergence over EXACT MATCHES, not over MONDO xrefs
    agreeing = sorted(hits)

    # conflict is only detectable among sources that CAN be compared:
    # those that bridged to a MONDO class. Sources with no common
    # identifier cannot be said to disagree.
    comparable: dict[str, list[str]] = {}
    for source, hit in hits.items():
        bridged = hit.get("mondo_id", "")
        if bridged:
            comparable.setdefault(bridged, []).append(source)

    if not hits:
        status = STATUS_UNRESOLVED
    elif len(comparable) > 1:
        status = STATUS_CONFLICT
    elif len(agreeing) >= 3:
        status = STATUS_HIGH
    elif len(agreeing) == 2:
        status = STATUS_MODERATE
    else:
        status = STATUS_LOW

    # canonical anchor: MONDO if any source bridged; else fall back
    # through the source priority. MONDO is a peer, not a gate.
    #
    # A CONFLICT emits NO ANCHOR. The whole content of a conflict is
    # that we do NOT know which class this is. Handing back an anchor
    # anyway -- picked by source priority from among disagreeing
    # sources -- would assert a resolution the system does not have,
    # and it would look exactly like a successful one downstream. The
    # candidates ARE the answer; a human resolves them.
    mondo_id = ""
    anchor = ""
    hierarchy_available = False

    if status == STATUS_CONFLICT:
        pass
    else:
        if len(comparable) == 1:
            mondo_id = next(iter(comparable))
        if mondo_id:
            anchor = mondo_id
            hierarchy_available = True
        else:
            for source in (SOURCE_SNOMED, SOURCE_MESH, SOURCE_ICD10):
                if source in hits:
                    anchor = f"{source.upper()}:{hits[source]['code']}"
                    break

    record = mondo_records.get(mondo_id, {})
    return {
        "query": name,
        "normalized": query,
        "status": status,
        "anchor": anchor,
        "mondo_id": mondo_id,
        "hierarchy_available": hierarchy_available,
        "label": record.get("label", ""),
        "parents": record.get("parents", []),
        "resolved_by": agreeing,
        "source_hits": {s: h["code"] for s, h in hits.items()},
        "candidates": sorted(comparable) if len(comparable) > 1 else [],
        "near_misses": near_misses,
    }


def load_sources() -> dict:
    """Load every on-disk index once. Returns a context dict."""
    mondo_terms, mondo_records, mondo_xrefs = _load_mondo()
    return {
        "mondo_terms": mondo_terms,
        "mondo_records": mondo_records,
        "mondo_xrefs": mondo_xrefs,
        "mesh_terms": _load_mesh(),
        "icd10_terms": _load_icd10(),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python3 condition_resolver.py \"disease name\"")
        return

    context = load_sources()
    print(f"loaded: {len(context['mondo_terms'])} MONDO terms, "
          f"{len(context['mesh_terms'])} MeSH terms, "
          f"{len(context['icd10_terms'])} ICD-10 terms")
    print()

    for name in sys.argv[1:]:
        result = resolve(
            name,
            context["mondo_terms"],
            context["mondo_records"],
            context["mondo_xrefs"],
            context["mesh_terms"],
            context["icd10_terms"],
        )
        print(f'=== "{result["query"]}"')
        print(f'    normalized : {result["normalized"]}')
        print(f'    status     : {result["status"]}')
        print(f'    anchor     : {result["anchor"]}  '
              f'{result["label"]}')
        print(f'    hierarchy  : {result["hierarchy_available"]}')
        print(f'    resolved_by: {result["resolved_by"]}')
        print(f'    source_hits: {result["source_hits"]}')
        if result["candidates"]:
            print(f'    CANDIDATES : {result["candidates"]}')
        for miss in result["near_misses"]:
            print(f'    near-miss  : [{miss["source"]}] '
                  f'{miss["reason"]} {miss["candidate"]}')
        print()


if __name__ == "__main__":
    main()
