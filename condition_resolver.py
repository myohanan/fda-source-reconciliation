"""
condition_resolver.py
---------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Resolves a disease NAME to a canonical condition object.

This is the ONE place identity happens. Nothing downstream re-derives
what disease a string refers to. The COA lookup, the drug lookup, and
the hierarchy matcher all receive a sealed resolved-condition object
and do their one job against it.

WHY THE UMLS METATHESAURUS, AND NOT FOUR VOCABULARIES SEPARATELY

An earlier design queried MONDO, MeSH, SNOMED, and ICD-10 as four
independent sources and crosswalked each hit to a shared identifier by
hand. It worked -- 79% of FDA's COA catalog -- but it was doing worse,
with more machinery, than asking one question of the right source.

The Metathesaurus already IS the union of ~200 vocabularies, already
cross-referenced, with the CUI (Concept Unique Identifier) as the
shared key. Querying it directly gets SNOMED, MeSH, ICD-10, MedDRA,
Orphanet, HPO, and the consumer vocabularies at once -- and gets the
crosswalk for free instead of rebuilding it from MONDO's xref columns,
which turned out to be unreliable (MONDO cross-references "hip
fracture" to SNOMED's "Fracture of proximal end of femur" -- a NARROWER
anatomical concept, and precisely the silent subtype substitution this
architecture exists to prevent).

What the Metathesaurus resolved that four separate vocabularies could
not, measured on FDA's own strings:

  Itch                                -> C0033774 Pruritus       (CHV)
  Chronic Heart Failure               -> C0264716                (SNOMED)
  Acute Bacterial Skin and Skin
    Structure Infection               -> C4552481                (MedDRA)
  Non-Cystic Fibrosis Bronchiectasis  -> C5243752                (MedDRA)
  Dystrophinopathy                    -> C5679787                (Orphanet)

MedDRA is FDA's OWN adverse-event terminology -- so FDA's indication
phrasing lands there and nowhere else. CHV is the Consumer Health
Vocabulary, which exists to bridge what patients say to what clinicians
code. That matters here because a COA measures what a PATIENT
experiences, and the catalog is named accordingly: "Itch," not
"Pruritus"; "Pain," not "Nociception." The lay/clinical split in FDA's
own condition names is not sloppiness. It tracks whether the entry is a
disease or an experience -- and it means a purely clinical vocabulary
will always miss half the catalog.

THE SEMANTIC GATE IS LOAD-BEARING, NOT DECORATIVE

Exact match alone is NOT sufficient at Metathesaurus scale, because
distinct concepts legitimately share a string. Searching "itch"
returns, ranked:

    C1422257  ITCH gene                      <- rank 1
    C1141025  ITCH protein, human            <- rank 2
    C0033774  Pruritus                       <- the answer

Taking the top exact hit resolves "itch" to a GENE. Only the semantic
type separates them:

    ITCH gene     -> Gene or Genome                     REJECT
    ITCH protein  -> Amino Acid, Peptide, or Protein    REJECT
    Pruritus      -> Sign or Symptom                    ACCEPT

So EVERY returned CUI is gated -- not just the top one -- and what
survives is the answer. The semantic type is a field the authority
PUBLISHES; the gate is therefore deterministic, not heuristic. It is
the same move as the gene resolver, where Orphanet's own disorder_type
drives strategy selection. No rule is written by hand; a typed field
decides.

The gate also kills, on real FDA queries:
    Fear of breast cancer               -> Mental Process
    Breast cancer screening declined    -> Finding-as-chart-observation
    Breast Cancer Risk Assessment Tool  -> Intellectual Product
    Varicose vein stripping             -> Therapeutic Procedure
Every one is a plausible-looking wrong answer -- the kind a reviewer
nods past.

ACCEPTED TYPES ARE A CLINICAL JUDGMENT

A COA measures what a patient experiences, so the accepted set is not
"Disease or Syndrome" alone. FDA has COAs for Itch and Pain (Signs or
Symptoms), Hip fracture (Injury or Poisoning), and Musculoskeletal pain
(which UMLS types, debatably, as a Finding). A disease-only gate would
refuse the catalog's own contents.

Finding is accepted despite also containing chart observations ("H/O:
hip fracture", "No varicose veins") because EXACT MATCH already excludes
those -- nobody queries a condition by typing "H/O: hip fracture." The
type gate's real job is catching concepts that WOULD exactly match a
legitimate query: genes, proteins, procedures, questionnaires.

EXACT MATCH ONLY

No ranked hits, no fuzzy scoring, no "closest" candidate. Settled with
evidence, not preference: SNOMED's rank-1 for "hip fracture" is
"Fracture of proximal end of femur" -- narrower, plausible, wrong, and
silent. And a substring matcher searching ICD-10 for "hip fracture"
matches "c-HIP FRACTURE" -- chip fracture of the talus.

STATUS LADDER

  RESOLVED             exactly one CUI survives the gate
  CONFLICT_DETECTED    two or more distinct CUIs survive -- a real
                       ambiguity, surfaced rather than guessed
  NOT_A_CONDITION      hits exist, but every one fails the type gate.
                       A FINDING, not a failure: FDA's string names a
                       gene, a procedure, a questionnaire, or a chart
                       observation.
  UNRESOLVED           no exact match in any of ~200 vocabularies. Also
                       a finding: FDA wrote a string no terminology
                       carries.

Confidence is carried by SOURCE COUNT -- how many independent
vocabularies contributed an atom to the surviving concept. One
vocabulary is weaker evidence than nine, and the object says so rather
than flattening it into a score.

MONDO IS FOR HIERARCHY, NOT IDENTITY

MONDO is not in UMLS, and it is the only source here carrying a usable
is_a hierarchy -- which is what makes "no COA for lung cancer, but a
qualified one for NSCLC, a subtype of your condition" possible. So it
is attached AFTER resolution, by name, purely to supply parents and
children.

It is never used for identity. Its xrefs are demonstrably unsafe for
that purpose (see the hip fracture case above). hierarchy_available
says plainly when MONDO has nothing to offer.

THE NEAR-MISS LOG IS A CALIBRATION INSTRUMENT

Every refusal is recorded with its source, candidate, and reason. It is
not debug output. It has already overturned two design decisions
(MONDO-as-gatekeeper; four-vocabularies-separately) and confirmed one
(exact-match-only). Read it before loosening any rule.

INPUTS
  UMLS REST API (UMLS_API_KEY in .env)  -- identity, via ~200 vocabularies
  fda_data/mondo_resolution_index.csv   -- hierarchy only
"""

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
MONDO_INDEX = os.path.join(DATA_DIR, "mondo_resolution_index.csv")

UMLS_BASE = "https://uts-ws.nlm.nih.gov/rest"
UMLS_TIMEOUT_SECONDS = 30
UMLS_PAUSE_SECONDS = 0.12
UMLS_PAGE_SIZE = 25

CTGOV_URL = "https://clinicaltrials.gov/api/v2/studies"
CTGOV_PAGE_SIZE = 30
CTGOV_MIN_TRIALS = 2
CTGOV_PAUSE_SECONDS = 0.35

STATUS_RESOLVED = "RESOLVED"
STATUS_CONFLICT = "CONFLICT_DETECTED"
STATUS_NOT_CONDITION = "NOT_A_CONDITION"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_LOOKUP_FAILED = "LOOKUP_FAILED"
STATUS_TRIAL_POPULATION = "RESOLVED_AS_TRIAL_POPULATION"
STATUS_GUIDANCE_DEFINED = "RESOLVED_BY_GUIDANCE"
STATUS_MULTINAME = "RESOLVED_FROM_MULTINAME"

# The vocabularies whose PURPOSE is lay / patient language.
# MedlinePlus is NLM's patient-facing health information. CHV is
# the Consumer Health Vocabulary, built by studying how people
# actually describe illness. They exist to answer exactly one
# question: what does a person MEAN by this word.
CONSUMER_VOCABULARIES = ("MEDLINEPLUS", "CHV")

# A COA measures what a patient experiences. Symptoms, injuries, and
# clinical findings are in scope. Genes, proteins, procedures, and
# questionnaires are not.
ACCEPTED_SEMANTIC_TYPES = {
    "Disease or Syndrome",
    "Neoplastic Process",
    "Mental or Behavioral Dysfunction",
    "Sign or Symptom",
    "Injury or Poisoning",
    "Anatomical Abnormality",
    "Pathologic Function",
    "Finding",
    "Congenital Abnormality",
    "Acquired Abnormality",
    "Cell or Molecular Dysfunction",
    "Experimental Model of Disease",
}

_PAREN_RE = re.compile(r"\s*\([^)]*\)")
_PUNCT_RE = re.compile(r"[^a-z0-9\s\-']")
_SPACE_RE = re.compile(r"\s+")

# Two or more complete "Name (ABBREV)" units concatenated into one
# cell. FDA does this when a disease has competing names and the
# trial must enroll all of them.
_MULTINAME_RE = re.compile(r"([^()]+?)\s*\(([A-Z][A-Za-z0-9\-]*)\)")

_concept_cache: dict[str, dict] = {}
_support_cache: dict[tuple[str, str], list[str]] = {}


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
    Deterministic normalization, applied identically everywhere.

    Drops FDA's embedded parenthetical abbreviation, lowercases, strips
    punctuation EXCEPT apostrophes and hyphens.

    The apostrophe exemption is not cosmetic. An earlier version
    stripped it, turning "Alzheimer's Disease" into "alzheimer s
    disease" and making four of the most recognizable diseases in
    medicine unresolvable. Most of what looks like a vocabulary gap is
    a normalization bug.
    """
    if not name:
        return ""
    text = _PAREN_RE.sub(" ", name)
    text = text.replace("\u2019", "'")
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


UMLS_MAX_RETRIES = 3


def _umls_get(path: str, **params) -> dict:
    """
    One authenticated UMLS call, with retry.

    Retries exist because the alternative is worse than slowness. A
    swallowed network failure in this function used to propagate all the
    way to a FINDING: the semantic-type lookup would return nothing, the
    gate would read "no type" as "not a condition," and the resolver
    would report that congestive heart failure IS NOT A DISEASE.

    A transient API failure must never become a statement about a
    disease. Retry first; if it still fails, raise -- and let the caller
    report LOOKUP_FAILED, which is a different fact.
    """
    params["apiKey"] = UMLS_API_KEY
    request = urllib.request.Request(
        f"{UMLS_BASE}{path}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "fda-recon/1.0",
                 "Accept": "application/json"})

    last = None
    for attempt in range(UMLS_MAX_RETRIES):
        try:
            with urllib.request.urlopen(
                    request, timeout=UMLS_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # A 404 is an ANSWER: the concept does not exist. Do not
            # retry it, and do not treat it as a failure.
            if exc.code == 404:
                raise
            last = exc
        except Exception as exc:  # noqa: BLE001
            last = exc
        if attempt < UMLS_MAX_RETRIES - 1:
            time.sleep(2 ** attempt)

    raise RuntimeError(f"UMLS unreachable after {UMLS_MAX_RETRIES} "
                       f"attempts: {type(last).__name__}")


def metathesaurus_search(query: str) -> tuple[list[dict], list[dict]]:
    """
    Exact search across the FULL Metathesaurus (~200 vocabularies).

    Returns (candidates, near_misses). A candidate is any concept whose
    name normalizes to the query. Everything else is a near miss --
    recorded, never used.
    """
    if not UMLS_API_KEY:
        return [], [{"source": "umls", "reason": "NO_API_KEY",
                     "candidate": ""}]
    try:
        payload = _umls_get(
            "/search/current", string=query, searchType="exact",
            returnIdType="concept", pageSize=UMLS_PAGE_SIZE)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # 404 is an ANSWER: nothing matched. Not a failure.
            return [], []
        raise
    except Exception:  # noqa: BLE001
        # Let it propagate. resolve() converts it to LOOKUP_FAILED --
        # which is "we could not check," NOT "this is not a condition."
        raise

    # UMLS's searchType=exact has ALREADY done the exact matching --
    # against every ATOM of every concept, across ~200 vocabularies.
    # What it returns is the concept's PREFERRED NAME, which is often
    # not the string you searched: "itch" returns "Pruritus"; "hip
    # fracture" returns "Hip Fractures"; "breast cancer" returns
    # "Malignant neoplasm of breast."
    #
    # An earlier version re-checked exactness against that preferred
    # name and rejected every correct answer. Do not re-derive what the
    # authority already determined. Exactness is UMLS's job here; the
    # SEMANTIC GATE and the VOTE COUNT are ours.
    candidates, near = [], []
    for result in payload.get("result", {}).get("results", []):
        cui, name = result.get("ui", ""), result.get("name", "")
        if not cui or cui == "NONE":
            continue
        candidates.append({"cui": cui, "name": name})
    time.sleep(UMLS_PAUSE_SECONDS)
    return candidates, near


def concept_detail(cui: str) -> dict:
    """Semantic types and atom count for one concept. Cached."""
    cached = _concept_cache.get(cui)
    if cached is not None:
        return cached

    detail = {"types": [], "atoms": 0, "name": "", "failed": False}
    try:
        result = _umls_get(f"/content/current/CUI/{cui}")["result"]
        detail["types"] = [
            s["name"] for s in result.get("semanticTypes", [])]
        detail["atoms"] = result.get("atomCount", 0)
        detail["name"] = result.get("name", "")
    except Exception:  # noqa: BLE001
        # THE CALL FAILED. That is NOT the same as "this concept has no
        # semantic type." An earlier version returned an empty type list
        # here, the gate read it as a rejection, and the resolver
        # reported NOT_A_CONDITION -- a finding about the DISEASE,
        # produced by a network hiccup.
        detail["failed"] = True

    _concept_cache[cui] = detail
    time.sleep(UMLS_PAUSE_SECONDS)
    return detail


def supporting_vocabularies(cui: str, query: str) -> list[str] | None:
    """
    Which vocabularies carry the QUERY STRING ITSELF as an atom of this
    concept?

    This is the convergence measure, and it is a VOTE COUNT, not a
    similarity score. The question is not "how close are these strings"
    -- it is "how many independent curated authorities call this concept
    by this name." That is the same evidentiary instrument as the
    two-citation minimum: corroboration from outside, countable, and
    traceable back to the specific body that asserted it.

    It is what distinguishes a real ambiguity from a curation artifact.
    Measured on FDA's own strings:

      "hip fracture"
          C0019557 Hip Fractures        13 vocabularies
          C0149531 Fracture of pelvis    1 vocabulary  (NCI alone)

      "breast cancer"
          C0006142 Malignant neoplasm   14 vocabularies
          C0678222 Breast Carcinoma      3 vocabularies

    Thirteen authorities against one is not a conflict. It is twelve
    bodies agreeing and one outlier -- NCI happens to list "hip
    fracture" as an atom under the PELVIS concept, which is a curation
    quirk, not a clinical claim.

    An earlier version never asked this question at all: it gated
    candidates by semantic type and then treated every survivor as an
    equal claimant. The evidence was sitting in UMLS and the resolver
    never looked. Both stray concepts survived, and both cases were
    reported as CONFLICT_DETECTED -- a false alarm produced by not
    measuring.
    """
    if not cui or not UMLS_API_KEY:
        return []
    cached = _support_cache.get((cui, query))
    if cached is not None:
        return cached

    sources: set[str] = set()
    failed = False
    try:
        atoms = _umls_get(
            f"/content/current/CUI/{cui}/atoms",
            pageSize=200, language="ENG")["result"]
        for atom in atoms:
            if normalize(atom.get("name", "")) == query:
                source = atom.get("rootSource", "")
                if source:
                    sources.add(source)
    except Exception:  # noqa: BLE001
        # Same failure class: an empty support list here would be read
        # as "only one vocabulary names this," the two-source minimum
        # would reject it, and the resolver would report a finding.
        failed = True

    if failed:
        _support_cache[(cui, query)] = None
        return None

    result = sorted(sources)
    _support_cache[(cui, query)] = result
    time.sleep(UMLS_PAUSE_SECONDS)
    return result


def load_mondo() -> tuple[dict, dict]:
    """
    (term -> mondo_id, mondo_id -> record). HIERARCHY ONLY.

    MONDO's xrefs are NOT loaded and must not be used for identity: it
    cross-references "hip fracture" to SNOMED's "Fracture of proximal
    end of femur," a narrower concept. Identity comes from UMLS.
    """
    terms: dict[str, str] = {}
    records: dict[str, dict] = {}
    with open(MONDO_INDEX, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mondo_id = row["mondo_id"]
            records[mondo_id] = {
                "mondo_id": mondo_id,
                "label": row["label"],
                "parents": [p for p in row["parents"].split("|") if p],
                "definition": row["definition"],
            }
            for term in [row["label"]] + row["exact_synonyms"].split("|"):
                key = normalize(term)
                if key:
                    terms.setdefault(key, mondo_id)
    return terms, records


def load_sources() -> dict:
    """Load the hierarchy index once."""
    mondo_terms, mondo_records = load_mondo()
    return {"mondo_terms": mondo_terms,
            "mondo_records": mondo_records}


def trial_population_lookup(query: str) -> tuple[int, list[str]]:
    """
    Does the trial registry carry this string as a registered condition?

    The registry is the authority on TRIAL POPULATIONS -- and FDA's COA
    Disease/Condition field is written in that language, because a COA
    exists to be used in a trial. "Acute Bacterial Skin and Skin
    Structure Infection" is not a disease name; it is a pathogen class,
    an anatomic site, and an acuity, bundled to define who enrolls. No
    clinical vocabulary has a REASON to carry it. The registry does.

    Normalization is applied to BOTH sides. The registry writes "Acute
    Bacterial Exacerbation of Chronic Bronchitis (ABECB)." -- with the
    abbreviation and a trailing period -- and an asymmetric comparison
    silently reports a false miss. That bug occurred here and nearly
    produced a false finding.
    """
    quoted = urllib.parse.quote(f'"{query}"')
    url = (f"{CTGOV_URL}?query.cond={quoted}"
           f"&pageSize={CTGOV_PAGE_SIZE}&fields=NCTId,Condition")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "fda-recon/1.0"})
        with urllib.request.urlopen(
                request, timeout=UMLS_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except Exception:  # noqa: BLE001
        return 0, []

    hits, seen = 0, set()
    for study in payload.get("studies", []):
        conditions = (study.get("protocolSection", {})
                      .get("conditionsModule", {})
                      .get("conditions", []))
        for condition in conditions:
            if normalize(condition) == query:
                hits += 1
                seen.add(condition)
    time.sleep(CTGOV_PAUSE_SECONDS)
    return hits, sorted(seen)


GUIDANCE_DEFINED_POPULATIONS = {
    "acute bacterial exacerbation of chronic bronchitis in patients "
    "with chronic obstructive pulmonary disease": {
        "label": "Acute Bacterial Exacerbation of Chronic Bronchitis "
                 "in Patients with COPD (ABECB-COPD)",
        "authority": "FDA Guidance for Industry, September 2012",
        "citation": "Acute Bacterial Exacerbation of Chronic "
                    "Bronchitis in Patients with Chronic Obstructive "
                    "Pulmonary Disease: Developing Drugs for Treatment",
        "note": "The COA field quotes the guidance TITLE verbatim. The "
                "population is defined by that document, not by any "
                "terminology. Per FDA's own SEALD review of COA DDT "
                "003: outpatients with a clinician diagnosis of "
                "ABECB-COPD; explicitly EXCLUDES COPD exacerbations "
                "caused by factors other than bacterial infection.",
    },
}


def split_multiname(name: str) -> list[str]:
    """
    Split a cell holding SEVERAL complete names for ONE disease.

    FDA does this when a disease has competing nomenclature and the
    trial must enroll patients diagnosed under any of them:

      "Chronic Fatigue Syndrome (CFS) Myalgic Encephalomyelitis (ME)
       Systemic Exertion Intolerance Disease (SEID)"

    Three names, three abbreviations, one disease, one cell. No
    vocabulary carries the concatenation, because the concatenation is
    not a name -- it is a LIST.

    This split is safe in a way the earlier "in patients with X"
    decomposition was NOT, and the difference matters. That one found
    GRAMMAR and generated MEANING -- it asserted a population
    restriction that FDA's own review contradicts. This one makes a
    STRUCTURAL hypothesis (these are separate names) and then TESTS it:
    each name is resolved independently, and they must CONVERGE ON THE
    SAME CONCEPT. Convergence is the confirmation. Divergence is a real
    conflict, and it goes to a human.

    The resolver does not decide what the string means. The authorities
    do.

    Requires >= 2 units to fire; a single "Name (ABBREV)" is an
    ordinary condition with an abbreviation, not a list.
    """
    units = _MULTINAME_RE.findall(name)
    if len(units) < 2:
        return []
    return [unit.strip() for unit, _abbrev in units if unit.strip()]


def guidance_defined(query: str) -> dict:
    """
    A small, explicit, auditable table of constructs that NO
    terminology names -- because a regulatory document defines them,
    not a vocabulary.

    THIS TABLE EXISTS BECAUSE AN INFERENCE FAILED, AND THE FAILURE IS
    WORTH RECORDING.

    An earlier version DECOMPOSED these strings with a regex:
    "X in patients with Y" -> core X, RESTRICTED TO Y. On ABECB-COPD it
    produced: core "Acute Bacterial Exacerbation of Chronic
    Bronchitis," restricted to "COPD."

    That is clinically incoherent. Chronic bronchitis IS a form of
    COPD -- one of the two classic phenotypes, alongside emphysema. The
    "restriction" restricts nothing; it is the PARENT CATEGORY of the
    core condition.

    And FDA's own SEALD review says what the phrase actually does. The
    clinical work is done by the word BACTERIAL, not by "in patients
    with COPD." The qualification explicitly EXCLUDES "COPD
    exacerbations caused by factors other than bacterial infection."
    The COPD phrase is simply part of the guidance's TITLE, which the
    COA field quotes verbatim.

    The regex found GRAMMAR and generated MEANING. It was deterministic
    and it was still wrong -- worse for being deterministic, because a
    reviewer would trust it. This is exactly the plausible-but-unearned
    output the architecture exists to prevent, and it slipped in
    through a pattern rule rather than a model call.

    So the decomposer is gone, and in its place is a CITATION. A string
    earns an entry here ONLY if a documented, non-terminology authority
    defines it -- a guidance, a statute, a program definition. If no
    such authority can be cited, the string does not go in the table:
    it stays NOT_A_CONDITION, and that is the honest answer.

    A named exception is not a hack. It is more defensible than any
    inference the resolver could make, because it points at the actual
    source of authority.
    """
    return GUIDANCE_DEFINED_POPULATIONS.get(query, {})


def _fallback(name: str, query: str, context: dict,
              near_misses: list[dict]) -> dict:
    """
    UMLS produced no surviving concept. Two authorities remain.

    FIRST, the TRIAL REGISTRY. FDA's COA condition field is written in
    the language of trial enrollment, because a COA exists to be used
    in a trial. The registry owns trial populations and carries every
    one that no clinical vocabulary does.

    SECOND, a REGULATORY DOCUMENT. A few constructs are defined by an
    FDA guidance rather than by any terminology. Those are named
    explicitly, with a citation.

    If neither holds, nothing in ~200 vocabularies, nothing in the
    trial registry, and no cited guidance names this string. That is a
    FINDING about FDA's catalog, not a failure of the resolver.
    """
    trials, registered = trial_population_lookup(query)
    if trials >= CTGOV_MIN_TRIALS:
        return _object(
            name, query, STATUS_TRIAL_POPULATION,
            label=registered[0] if registered else name,
            sources=["CLINICALTRIALS.GOV"],
            atom_count=trials,
            near_misses=near_misses)

    names = split_multiname(name)
    if names:
        resolved = []
        for unit in names:
            unit_result = resolve(unit, context)
            if unit_result["status"] == STATUS_RESOLVED:
                resolved.append(unit_result)
            near_misses.extend(unit_result["near_misses"])

        cuis = {r["cui"] for r in resolved}
        if len(cuis) == 1:
            # every name that resolved landed on the SAME concept.
            # That is the confirmation the split was correct.
            winner = resolved[0]
            winner["query"] = name
            winner["normalized"] = query
            winner["status"] = STATUS_MULTINAME
            winner["multiname_units"] = names
            winner["near_misses"] = near_misses
            return winner
        if len(cuis) > 1:
            return _object(name, query, STATUS_CONFLICT,
                           near_misses=near_misses,
                           candidates=sorted(cuis))

    entry = guidance_defined(query)
    if entry:
        return _object(
            name, query, STATUS_GUIDANCE_DEFINED,
            label=entry["label"],
            sources=[entry["authority"]],
            citation=entry["citation"],
            authority_note=entry["note"],
            near_misses=near_misses)

    # Confirmed on FDA's catalog for exactly one entry: "Recovery from
    # surgery and anesthesia," whose Context of Use is "patients
    # undergoing ALL FORMS of surgery and anesthesia" -- not a
    # population -- and whose COA FDA declined at Letter of Intent. The
    # field holds a clinical CONTEXT, not a condition.
    return _object(name, query, STATUS_NOT_CONDITION,
                   near_misses=near_misses)


def consumer_choice(contest: list[dict]) -> dict:
    """
    Two concepts both survived the gate. Which one does the term MEAN?

    NOT a vote count. NOT a threshold. The same dispatch used
    everywhere in this resolver: THE AUTHORITY THAT OWNS THE QUESTION
    DECIDES. For a disease name a person would type, the owners are
    MedlinePlus and CHV -- that is their entire purpose.

    Measured on real queries a vote count could NOT decide:

      breast cancer   C0006142  Malignant neoplasm of breast
                                [CHV, MEDLINEPLUS]          <- chosen
                      C0678222  Breast Carcinoma
                                [CHV]
          Both carry CHV. Only one carries MEDLINEPLUS.

      lung cancer     C0242379  Malignant neoplasm of lung  <- chosen
                      C0684249  Carcinoma of lung        (no consumer)

      stroke          C0038454  Cerebrovascular accident    <- chosen
                      C5977286  Stroke (heart beat)      (no consumer)
          A cardiac rhythm term. A homonym, not a contender. No
          consumer source points at it, because no person means that.

      diabetes        C0011849  Diabetes Mellitus           <- chosen
                      C0011847  Diabetes                 (no consumer)
          C0011847 is the broader taxonomic parent, which INCLUDES
          diabetes insipidus. No patient saying "diabetes" means
          insipidus, and the consumer vocabularies encode that. That IS
          their job.

    A VOTE COUNT COULD NOT HAVE DONE THIS. Breast cancer is 14 vs 3.
    Diabetes is 6 vs 5. Any margin tuned to separate the first would
    silently pick a winner in the second; any margin loose enough to
    defer on the second would fail on the first. The counts are not the
    signal. The SOURCE is.

    Returns the chosen candidate, or {} -- in which case it is a real
    conflict and a human decides.
    """
    consumer = set(CONSUMER_VOCABULARIES)
    with_consumer = [c for c in contest if set(c["support"]) & consumer]

    if len(with_consumer) == 1:
        return with_consumer[0]

    if len(with_consumer) > 1:
        # Both carry CHV. MedlinePlus is the narrower, patient-facing
        # authority; if exactly one has it, that is the term's meaning.
        with_mlp = [c for c in with_consumer
                    if "MEDLINEPLUS" in c["support"]]
        if len(with_mlp) == 1:
            return with_mlp[0]

    return {}


def resolve(name: str, context: dict) -> dict:
    """
    Resolve one disease name. Returns a sealed condition object.
    Never re-derives, never blends, never guesses.
    """
    query = normalize(name)
    if not query:
        return _object(name, "", STATUS_UNRESOLVED, near_misses=[{
            "source": "normalizer",
            "reason": "EMPTY_AFTER_NORMALIZATION",
            "candidate": name}])

    # A LOOKUP FAILURE IS NOT A FINDING.
    #
    # Every UMLS call below can fail. An earlier version swallowed those
    # failures and returned empty results -- which the gates read as
    # rejections, and the resolver reported NOT_A_CONDITION. A network
    # hiccup became a statement that congestive heart failure is not a
    # disease.
    #
    # "We checked and this is not a condition" and "we could not check"
    # are completely different facts. The system must never confuse
    # them, and it must never report the first when it means the second.
    try:
        candidates, near_misses = metathesaurus_search(query)
    except Exception as exc:  # noqa: BLE001
        return _object(name, query, STATUS_LOOKUP_FAILED, near_misses=[{
            "source": "umls",
            "reason": "SEARCH_FAILED",
            "candidate": f"{type(exc).__name__}"}])

    if not candidates:
        return _fallback(name, query, context, near_misses)

    # gate EVERY candidate, not just the top one
    surviving = []
    for candidate in candidates:
        detail = concept_detail(candidate["cui"])
        if detail["failed"]:
            return _object(name, query, STATUS_LOOKUP_FAILED,
                           near_misses=near_misses + [{
                               "source": "umls",
                               "reason": "SEMANTIC_TYPE_LOOKUP_FAILED",
                               "candidate": candidate["cui"]}])
        types = detail["types"]
        if not types:
            near_misses.append({
                "source": "umls", "reason": "NO_SEMANTIC_TYPE",
                "candidate": f"{candidate['cui']} {candidate['name']}"})
            continue
        if ACCEPTED_SEMANTIC_TYPES.intersection(types):
            surviving.append({**candidate, "types": types,
                              "atoms": detail["atoms"]})
        else:
            near_misses.append({
                "source": "umls", "reason": "TYPE_REJECTED",
                "candidate": (f"{candidate['cui']} {candidate['name']} "
                              f"{types}")})

    if not surviving:
        return _object(name, query, STATUS_NOT_CONDITION,
                       near_misses=near_misses,
                       candidates=[c["cui"] for c in candidates])

    # SCORE every survivor: how many vocabularies call it by this name?
    for candidate in surviving:
        support = supporting_vocabularies(candidate["cui"], query)
        if support is None:
            return _object(name, query, STATUS_LOOKUP_FAILED,
                           near_misses=near_misses + [{
                               "source": "umls",
                               "reason": "SUPPORT_LOOKUP_FAILED",
                               "candidate": candidate["cui"]}])
        candidate["support"] = support
        candidate["n_support"] = len(support)

    surviving.sort(key=lambda c: -c["n_support"])
    contest = [
        {"cui": c["cui"], "name": c["name"],
         "n_support": c["n_support"], "support": c["support"]}
        for c in surviving
    ]

    # THE TWO-SOURCE MINIMUM.
    #
    # A concept needs at least TWO independent vocabularies calling it
    # by this name to be a contender. One vocabulary is not evidence.
    #
    # This is NOT a tuned threshold, and it was deliberately not chosen
    # by fitting a number to examples. The corpus was run first, with no
    # rule at all, and every contested case was examined. The result:
    #
    #   Alopecia areata   21 vocabs  vs  1  (Alopecia) and 1 (Patchy alopecia)
    #   Cancer            22 vocabs  vs  0
    #                     (Neoplasms -- NOTHING calls it that)
    #   Obesity           33 vocabs  vs  1  (an OMIM genetic LOCUS)
    #   Hip fracture      14 vocabs  vs  1  (NCI filing it under PELVIS)
    #
    # There is no close case in the corpus. Not one. The margins are
    # 14x, 21x, 33x, and infinite -- so a 2x rule, a 5x rule, and a
    # strictly-greater rule would all give identical answers, and any
    # number picked would be unjustified by the data.
    #
    # So the rule is not a margin at all. It is the same evidentiary
    # standard already used for endpoints: TWO independent sources, or
    # it does not count. Every single-vocabulary runner-up above is
    # plainly wrong on inspection -- a curation quirk, a genetic locus,
    # a parent concept. One authority asserting a name is not
    # corroboration; it is an artifact waiting to be believed.
    #
    # If a future query produces two contenders with 8 and 7 votes,
    # that is a REAL ambiguity, it goes to a human, and THAT is when
    # the boundary gets learned -- from a case that actually has one.
    contenders = [c for c in surviving if c["n_support"] >= 2]

    for c in surviving:
        if c["n_support"] < 2:
            near_misses.append({
                "source": "umls",
                "reason": "SINGLE_VOCABULARY_ONLY",
                "candidate": (f'{c["cui"]} {c["name"]} '
                              f'({c["n_support"]} vocab: {c["support"]})'),
            })

    if not contenders:
        # UMLS found concepts, but none had two independent
        # vocabularies naming it. Before calling this unresolved, ask
        # the registry: a single-vocabulary hit from ORPHANET or MedDRA
        # is often the DOMAIN OWNER, not an artifact -- and the trial
        # registry confirms it independently.
        return _fallback(name, query, context, near_misses)

    if len(contenders) > 1:
        # A vote count cannot adjudicate between two concepts that are
        # both real. Ask the authority that owns the question.
        chosen = consumer_choice(contenders)
        if chosen:
            consumer = set(CONSUMER_VOCABULARIES)
            for c in contenders:
                if c["cui"] != chosen["cui"]:
                    hits = sorted(set(c["support"]) & consumer)
                    near_misses.append({
                        "source": "consumer_vocabulary",
                        "reason": "NOT_THE_LAY_MEANING",
                        "candidate": (f'{c["cui"]} {c["name"]} '
                                      f'({c["n_support"]} vocab, '
                                      f'consumer: {hits})'),
                    })
            contenders = [chosen]
        else:
            return _object(name, query, STATUS_CONFLICT,
                           near_misses=near_misses,
                           candidates=[c["cui"] for c in contenders],
                           contest=contest)

    winner = contenders[0]
    mondo_id = context["mondo_terms"].get(query, "")
    record = context["mondo_records"].get(mondo_id, {})

    return _object(
        name, query, STATUS_RESOLVED,
        cui=winner["cui"],
        label=winner["name"],
        semantic_types=winner["types"],
        sources=winner["support"],
        atom_count=winner["atoms"],
        mondo_id=mondo_id,
        parents=record.get("parents", []),
        near_misses=near_misses,
        contest=contest,
    )


def _object(query: str, normalized: str, status: str, **kwargs) -> dict:
    """The sealed condition object. One shape, always."""
    mondo_id = kwargs.get("mondo_id", "")
    return {
        "query": query,
        "normalized": normalized,
        "status": status,
        "cui": kwargs.get("cui", ""),
        "label": kwargs.get("label", ""),
        "semantic_types": kwargs.get("semantic_types", []),
        "sources": kwargs.get("sources", []),
        "n_sources": len(kwargs.get("sources", [])),
        "atom_count": kwargs.get("atom_count", 0),
        "mondo_id": mondo_id,
        "parents": kwargs.get("parents", []),
        "hierarchy_available": bool(mondo_id),
        "candidates": kwargs.get("candidates", []),
        "contest": kwargs.get("contest", []),
        "citation": kwargs.get("citation", ""),
        "multiname_units": kwargs.get("multiname_units", []),
        "authority_note": kwargs.get("authority_note", ""),
        "near_misses": kwargs.get("near_misses", []),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python3 condition_resolver.py "disease name"')
        return

    context = load_sources()
    if not UMLS_API_KEY:
        print("ERROR: no UMLS_API_KEY in .env. Identity resolution "
              "requires it.")
        return

    for name in sys.argv[1:]:
        result = resolve(name, context)
        print(f'=== "{result["query"]}"')
        print(f'    normalized  : {result["normalized"]}')
        print(f'    status      : {result["status"]}')
        print(f'    cui         : {result["cui"]}  {result["label"]}')
        print(f'    types       : {result["semantic_types"]}')
        print(f'    n_sources   : {result["n_sources"]}  '
              f'({result["atom_count"]} atoms)')
        print(f'    sources     : {result["sources"][:12]}')
        print(f'    mondo       : {result["mondo_id"]}  '
              f'hierarchy={result["hierarchy_available"]}')
        if result["citation"]:
            print(f'    CITATION    : {result["citation"]}')
        if result["contest"] and len(result["contest"]) > 1:
            print('    CONTEST     :')
            for c in result["contest"]:
                print(f'        {c["n_support"]:>2} vocabs  '
                      f'{c["cui"]}  {c["name"][:40]:<40} '
                      f'{c["support"][:6]}')
        for miss in result["near_misses"][:6]:
            print(f'    near-miss   : [{miss["source"]}] '
                  f'{miss["reason"]} {miss["candidate"]}')
        extra = len(result["near_misses"]) - 6
        if extra > 0:
            print(f'    near-miss   : ... and {extra} more')
        print()


if __name__ == "__main__":
    main()
