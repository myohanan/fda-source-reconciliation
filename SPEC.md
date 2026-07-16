# SPEC.md — FDA Source Reconciliation

For engineers: what each tool takes, what it returns, what it
guarantees, and what it refuses to do.

---

## 0. The stucutre

Single-function tools with sealed handoffs. Each does exactly one
thing, emits a sealed result.

No tool re-derives what an earlier tool determined. The orchestrator
routes; it does not adjudicate. That is what keeps every output
traceable to the authority that produced it.

There is no generative step anywhere in the pipeline: key joins, coded
lookups, typed-field gates, vote counts over declared vocabularies. A
reviewer can walk any determination back to its cause.

No synonym list is created or maintained. Identity and relationships
are resolved through published vocabularies (~200 in UMLS) and
taxonomies (six hierarchy sources), so "CHF," "congestive heart
failure," and "carcinoma of lung" resolve without anyone writing a
mapping. When FDA adds a COA condition, nobody adds synonyms; when a
user types a lay term or an alternate phrasing, resolution and the
hierarchy handle it. The benefit is maintainability: the system scales
as the vocabularies and the catalog grow, with no synonym table to keep
current. A synonym list is a reasonable approach for a small, stable
vocabulary; at the scale of medicine, drawing on the published
vocabularies avoids the upkeep it would take to build and maintain one.

---

## 1. condition_resolver

**Input:** a disease name (any string, any vocabulary, lay or
clinical).

**Output:** a sealed condition object.

    {
      query               the string as given
      normalized          deterministic normalization
      status              see below
      cui                 UMLS Concept Unique Identifier
      label               the concept's preferred name
      semantic_types      what kind of thing this is
      sources             which vocabularies named it
      n_sources           how many
      mondo_id            if MONDO carries it
      hierarchy_available bool
      candidates          on CONFLICT_DETECTED
      near_misses         every refusal, with its reason
    }

**Statuses, and what each means:**

| Status | Meaning |
|---|---|
| `RESOLVED` | One concept survived the gates. |
| `RESOLVED_AS_TRIAL_POPULATION` | No vocabulary carries it; ClinicalTrials.gov registers it. It is an enrollment definition, not a disease entity. |
| `RESOLVED_FROM_MULTINAME` | The field held several names for one disease; all resolved to the same concept. |
| `RESOLVED_BY_GUIDANCE` | Defined by a cited FDA guidance, not by any terminology. |
| `CONFLICT_DETECTED` | Two or more concepts survived and no authority could adjudicate. A human decides; the tool does not guess. |
| `NOT_A_CONDITION` | Hits exist but every one failed the semantic gate. The string names a gene, a procedure, a questionnaire, or a chart observation. |
| `UNRESOLVED` | Nothing in ~200 vocabularies, nothing in the registry, no cited guidance. |

**Guarantees:**
- Exact match only. No ranked hits, no fuzzy scoring.
- Every candidate is gated by its semantic type — a field the authority
  publishes, not a rule written by hand.
- A concept needs two independent vocabularies naming it to be a
  contender. One is not enough.
- Every refusal is logged in `near_misses`, with its source and reason.

**Refuses to:**
- Guess when two concepts are both real and no authority discriminates.
- Accept a ranked top hit. SNOMED's rank-1 for "hip fracture" is
  "Fracture of proximal end of femur" — narrower, plausible, wrong,
  and silent.

---

## 2. coa_lookup

**Input:** a sealed condition object.
**Output:** FDA's COAs for it, or an honest none.

    {
      status         COA_FOUND | NO_COA | CONDITION_UNRESOLVED
      cui, label
      coas[]         instrument, concept, context_of_use, coa_type,
                     stage, qualified, documents[]
      catalog_size   how many distinct conditions were checked
      note           on NO_COA, the honest statement
    }

The join is on whatever identity the resolver settled on — a CUI, or a
normalized trial-population name. Not on a CUI alone. An earlier
version joined on CUI only and silently abandoned the seven conditions
that ClinicalTrials.gov had resolved.

`NO_COA` is a first-class answer, not a failure. It reads:

    Resolved to C0006142 (Malignant neoplasm of breast). Checked all 52
    distinct conditions in the FDA COA catalog. FDA has no qualified or
    in-process clinical outcome assessment for this condition.

`CONDITION_UNRESOLVED` is a different fact, and says so:

    This is not a statement that FDA has no COA -- it is a statement
    that we could not determine what disease this is.

Those two are indistinguishable from a blank, so the distinction is
stated explicitly.

Context of use: the catalog's column is a lossy summary. The KCCQ's
reads "Patients with CHF." Its qualification statement reads "stage C &
D heart failure, NYHA Classes I-IV, HFpEF or HFrEF." The document
governs; this tool points at it rather than summarizing it.

---

## 3. hierarchy_matcher

**Input:** two CUIs.
**Output:** their relation, per source and converged.

    EXACT | PARENT | CHILD | SIBLING | ANCESTOR | DESCENDANT
    UNRELATED | NO_HIERARCHY

Six sources are asked (SNOMED, MeSH, NCIt, ICD-10-CM, MedDRA, MONDO),
and convergence decides: one source cannot overrule three.

`NO_HIERARCHY` is a reported state with its reason. Seven of FDA's 54
conditions have no parent in any source — and they are exactly the
trial populations. That is a category fact, not a coverage gap: a trial
enrollment definition has no taxonomic parent because it is not the
kind of thing that has one.

**The defining-attributes sibling gate (SNOMED).** A sibling is inferred
through a shared parent, so it is only as meaningful as that parent. Two
diseases that share a real disease-family parent are siblings; two that
share only a classification axis — an inheritance pattern, a body-site
grouping, a generic "disorder" node — are not. The discriminator is
SNOMED's own concept model: a parent with at least one defining
attribute (finding site, associated morphology, etc.) is a clinical
entity; a parent with none is a grouper.

    Heart failure (84114007)                     3 defining attributes  → real
    Malignant neoplasm of lung (363358000)       2 defining attributes  → real
    Autosomal recessive hereditary disorder      0 defining attributes  → grouper
        (85995004)

A SNOMED sibling whose shared parents are all groupers is resolved to
`UNRELATED`. This keeps congestive/chronic heart failure (shared parent
"Heart failure," defined) while dropping the Gaucher-disease/cystic-
fibrosis false sibling (shared parent "Autosomal recessive hereditary
disorder," a grouper). It is a published, categorical gate — the
presence or absence of a concept model, not a threshold on a count —
and it is the hierarchy analogue of the resolver's semantic-type gate. The
defined/grouper map is built once by `build_defining_attributes.py` (see
below) and read from `fda_data/snomed_defined.json`; if that file is
absent the gate disables cleanly and the pre-gate behavior returns.

**Refuses to:**
- Report shared remote ancestry as a relation. Every concept shares the
  root. Congestive and chronic heart failure share twenty SNOMED
  ancestors including "Disorder of thorax." That is not a relationship.
- Report a sibling that rests only on a grouper parent (see the gate
  above). Sharing a classification axis is not a relationship.
- Say an instrument applies. Surfacing a neighbor is navigation, not
  authorization. Whether a COA qualified for chronic heart failure is
  valid in an acute decompensated trial is a regulatory judgment, and
  FDA makes it, not this tool.

---

## 4. neighbor_lookup

**Input:** a sealed condition object (the user's, from the resolver)
plus the catalog of sealed conditions.
**Output:** the catalog conditions structurally related to it, and how.

    {
      status        NEIGHBORS_FOUND | NO_NEIGHBOR_IN_CATALOG
                    | NO_HIERARCHY
      cui           the identity searched from
      neighbors[]   condition, cui, relation, agreeing_sources
      note          on any empty status, the honest reason
      degraded_sources[]   sources whose lookup failed this search,
                           recorded for calibration, per source
    }

Runs only when coa_lookup found no COA for the user's condition. It
answers: FDA has nothing for your disease -- does it have something for
a related one, and how is it related?

**Statuses, and what each means:**

| Status | Meaning |
|---|---|
| `NEIGHBORS_FOUND` | One or more catalog conditions relate structurally. Each is surfaced with its relation and the sources that agreed. |
| `NO_NEIGHBOR_IN_CATALOG` | The identity HAS a CUI, the six-source search ran to completion against every catalog condition, and none related. A verified absence -- checked, found none -- not a blank. |
| `NO_HIERARCHY` | The identity has no CUI (a trial population, a guidance-defined construct). It cannot be related because it is not the kind of thing that has a taxonomic parent. A category fact, not a coverage gap. |

**The canonical-object principle.** Every catalog condition was resolved
once, at catalog build, into a sealed identity. The user's disease was
resolved once, in Step 1. This tool compares a sealed CUI against sealed
CUIs. It never reads a neighbor's name and never calls
condition_resolver. Identity is a settled upstream concern; a
downstream step does not re-solve it.

**Guarantees:**
- Every comparison uses `hierarchy_matcher` -- six sources, convergence
  decides, one source cannot overrule three. Unchanged from section 3.
- Compares sealed CUI to sealed CUI. No identity is re-derived.
- Only immediate structural relations are reported -- parent, child,
  sibling, bounded ancestry. Never remote shared ancestry (section 3).
- Every empty result carries its reason. `NO_NEIGHBOR_IN_CATALOG` and
  `NO_HIERARCHY` are different facts and say so.
- A source that answers "does not carry this concept" has not voted --
  a content condition, not a degradation. A source that errors is a
  degradation, recorded in `degraded_sources` for calibration, per
  source. The two are never collapsed.

**Refuses to:**
- Attach COAs. That is neighbor_coa_lookup's job.
- Say a surfaced instrument applies. Navigation, not authorization --
  the regulatory judgment is FDA's.
- Relate a CUI-less identity. Returns `NO_HIERARCHY` with its reason.
- Stop the run on a source failure. It degrades that source to a
  recorded UNKNOWN and continues with the sources that answered.

---

## 5. neighbor_coa_lookup

**Input:** the sealed neighbor result (from neighbor_lookup) plus the
catalog.
**Output:** the same neighbors, each with its COAs attached.

    {
      status        ATTACHED | NOTHING_TO_ATTACH
      neighbors[]   each neighbor unchanged, plus:
                      coas[]   the COAs the catalog holds for this
                               neighbor's CUI -- instrument, concept,
                               context_of_use, coa_type, stage,
                               qualified. Verbatim from the catalog.
    }

Finding a related condition and attaching its COAs are two jobs, kept in
two tools, so a failure in one is diagnosable without reading the other.

**Guarantees:**
- COAs come verbatim from the catalog. Nothing re-derived, nothing
  summarized -- the document governs (section 2).
- The relation and CUI from neighbor_lookup pass through SEALED and
  unchanged. This tool does not re-compute a relation.
- A neighbor whose catalog entry holds no COAs is kept, with
  `coas: []` -- a stated empty, not a silent drop. "A sibling exists and
  it too has no COA" is a verified fact about the neighborhood. What to
  display of these is a presentation concern (the finding), not this
  tool's -- the tool reports completely.

**Refuses to:**
- Re-compute the relation. It is already sealed.
- Say an instrument applies, or judge fit.
- Drop a neighbor silently.

---

## 6. drug_lookup

**Input:** a sealed condition object.
**Output:** approved drugs, by two independent routes.

    ROUTE 1  CODED    ApplNo -> rxcui -> MED-RT may_treat -> MeSH -> CUI
    ROUTE 2  PROSE    ApplNo -> openFDA indications_and_usage -> text

They are not a primary and a backup; they answer different questions.

- **Coded** is fully coded; no text is read. But MED-RT's `may_treat` is
  broader than an approved indication — it captures off-label and
  class-level use, and returns artifacts (aripiprazole `may_treat` "Drug
  Hypersensitivity", a contraindication).
- **Prose** is the approved label — the regulatory truth. But it is a
  string match, and that is the one place in this system a silent false
  positive can enter.

Every drug carries which route found it, and the counts are never
merged. Cardiolite — a cardiac imaging agent — matches "breast" in its
label; it appears in the prose-only bucket with its indication text
printed, so a reader can see what it is.

Agreement is corroboration; disagreement is a finding.

---

## 7. endpoint_search

**Input:** an instrument name.
**Output:** every trial that registered it as an outcome measure — with
the verbatim outcome text.

Never a boolean, never a count alone. The reason:

    FDA's qualified asthma COA is the Asthma DAYTIME Symptom Diary
    (6 items, 0-10, C-Path).

    NAVIGATOR -- the pivotal Phase 3 that got Tezspire approved --
    registered "Change from baseline in Asthma Symptom Diary."

    It is a different instrument: ten items, scored 0-4, Globe et al
    2015.

    A string matcher called it a hit, and nothing about the output would
    have looked broken.

Reconciliation: the retrieved count is checked against the registry's
reported total. An incomplete retrieval is reported as an error, not
passed over. If the registry reports no total, completeness cannot be
verified, and that is reported too.

---

## 7a. drug_resolver

**Input:** a free-text intervention string (from a trial record).
**Output:** a canonical drug identity, or a labeled non-resolution.

    RESOLVED                  → ingredient_rxcui, ingredient (name)
    UNRESOLVED_NOT_A_DRUG     → a control/non-drug (placebo, standard of
                                care, GDMT, monotherapy...)
    UNRESOLVED_NOT_IN_RXNORM  → a drug RxNorm does not carry (an
                                investigational code)

The canonical-object pattern applied to drugs, exactly parallel to
condition_resolver applied to diseases: a free-text string is not an
identity. ClinicalTrials.gov intervention names are messy — "Dapagliflozin",
"Dapagliflozin 10mg Tab", "Dapagliflozin (Forxiga)", "dapagliflozine" are
one drug written nine ways. Each resolves to its RxNorm ingredient
rxcui, so the nine collapse to one. Combinations keep all ingredients
sorted into one canonical key: "sacubitril/valsartan" stays distinct from
either single drug; "LCZ696 (sacubitril/valsartan)" folds in via its
parenthetical.

**Guarantees:**
- Controls fall out because they do not resolve to a drug ingredient —
  a principled test, not a maintained blocklist of phrases.
- An investigational drug RxNorm lacks is kept and labeled
  `NOT_IN_RXNORM`, never silently dropped. "Could not resolve" and "not
  a drug" are different facts with different names.
- Same RxNav access pattern as `download_rxnorm_indications` (no key,
  paced, cached to `fda_data/drug_resolve_cache.json`).

---

## 7b. coa_drug_link

**Input:** a COA instrument name.
**Output:** the FDA-approved drugs whose trials used the instrument.

Given a COA instrument, finds the ClinicalTrials.gov trials that
registered it as an outcome measure, reads each trial's DRUG/BIOLOGICAL
interventions, resolves each via `drug_resolver` to a canonical
ingredient, and reports the approved ones with a per-drug trial count.

This is a co-occurrence claim and nothing more: the drug was tested in
trials that used this COA. It does not claim the drug was approved on
the basis of the COA, or that the COA was a pivotal endpoint — the COA
may have been secondary or exploratory. Same flat-statement-of-fact
discipline as the rest of the system.

**Guarantees:**
- Filtered to FDA-approved drugs (openFDA approved-label set, matched at
  ingredient level). Investigational or discontinued compounds drop out
  because they are not approved.
- If the approved set cannot load, approval status is `UNKNOWN` and no
  filtering runs (all drugs shown, labeled) — never a false "unapproved."
- Standalone. It does not touch the reconciliation orchestrator.

---

## 7c. trial_instruments  (PROTOTYPE)

**Input:** a disease name and its approved-drug generic names.
**Output:** the outcome measures those drugs' trials used, each flagged
qualified COA / CDISC-recognized instrument / other, with trial counts.

For a disease's approved drugs, pulls the ClinicalTrials.gov trials and
their registered outcome measures, and classifies each measure against
two published lists: the qualified-COA catalog and CDISC's instrument
terminology (`fda_data/cdisc_instruments.csv`). Matches are
word-boundary (a short acronym like "ESS" cannot match inside
"assessment"); scaffolding terms (CTCAE, adverse-event, PK, vital-sign)
are excluded from the instrument buckets. Near-duplicate phrasings of
the same instrument collapse under one canonical name.

**Co-occurrence only** — an instrument appeared as an outcome measure in
a trial of an approved drug; never a claim the drug was approved on it.
The qualified/not flag is factual (is it in FDA's qualified set), not a
verdict on the instrument's value.

**Status: PROTOTYPE.** The classification is only as good as the string
alignment between trial phrasing and CDISC's canonical names; CDISC's
terminology is questionnaire-weighted and thin on performance tests, so
some real instruments fall to "other." It surfaces the shape of what a
disease's trials measured; it is not a demo centerpiece. The empirical
finding it produced (e.g. no DMD approval trial used a qualified COA)
was verified manually and does not depend on the tool.

---

## 7d. group_measures  (utility)

**Input:** a flat list of outcome-measure titles.
**Output:** the same titles grouped under shared leading words.

A readability utility: titles that share their first N words are
grouped under one header, so a long dump becomes a short set of headers.
Pure text grouping — no classification, no external authority, tunable
by word count. Used to make a long measure list scannable.

---

## 7e. list_coas

**Input:** optional filters (`--search`, `--stage`, `--type`,
`--submissions`, `--compendium`).
**Output:** a count summary, then the matching COAs from both resources.

The full-list / search view over FDA's two COA resources —
`coa_submissions.csv` (the qualification pipeline, grouped by stage) and
`coa_compendium.csv` (the finished/qualified set). Every query leads
with a count summary (stage and type breakdown) and then the full
grouped listing; a front end decides how much to reveal. Filters are
composable. Reads both files with a proper CSV parser (context-of-use
fields carry embedded commas). The two resources share no key — showing
them together is the point.

**This tool covers three doors at once:** the full list (no args), COA-
name / instrument search (`--search "SDMT"`), and filtered browsing
(`--stage`, `--type`). No separate COA-name lookup is needed.

---

## 8. Orchestration — two views

The tools compose into two orchestrations over the same sealed identity.
They share every underlying tool; they differ in scope and framing.

- **`reconciliation_orchestrator`** — the expansive everything-view.
  Resolves, checks COAs, finds neighbors, lists approved drugs for the
  disease, checks endpoint usage, and assembles the finding.
- **`coa_orchestrator`** — the tight, COA-focused view (the demo MVP).
  Everything it shows is shaped by the COA: for each COA in the picture
  (the disease's own, or a neighbor's), it pulls that instrument's
  trials and the approved drugs those trials tested. When there is no
  COA anywhere, it says so and shows nothing on drugs or trials, because
  there is no COA to hang them on.

### 8a. reconciliation_orchestrator

Fixed sequence, sealed handoffs, degradation rather than halt.

    Step 1   condition_resolver     sealed identity
    Step 2   coa_lookup
             neighbor_lookup        only if Step 2 found nothing
             neighbor_coa_lookup    only if neighbors were found
    Step 3   drug_lookup
    Step 4   endpoint_search        only if Step 2 found a COA
    Step 5   the finding            assembled, not re-reasoned

The neighbor search is suppressed when a COA exists. Ranging outward to
offer alternatives would substitute the system's judgment for FDA's, on
criteria nobody gave it.

A tool that fails degrades to a sealed UNKNOWN and the pipeline
continues; it does not emit a false negative.

    "We checked and FDA has no COA"     and
    "We could not check"

are completely different facts, and a user cannot tell them apart from
a blank. The schema records which one happened, in `steps` and
`calibration.degraded_steps`.

### 8b. coa_orchestrator

Same tools, COA-shaped scope. Cache-backed for demos.

    resolve → coa_lookup
              (if no own COA) neighbor_lookup + neighbor_coa_lookup
              per COA instrument in the picture:
                  endpoint_search   → its trials, primary vs secondary
                  coa_drug_link     → approved drugs those trials tested
              (no COA anywhere)     → honest empty; no drugs, no trials

Every drug and trial traces to a COA. A disease with its own COA shows
that COA's evidence; a disease with none shows a related condition's COA
(sibling/child/ancestor) with the same evidence; a disease with no COA
anywhere gets the plain "nothing here, nothing nearby" — a verified
absence, stated as such.

Qualified-but-unused COAs are a finding, not noise. A qualified COA
that no trial ever used (zero trials in the registry) is surfaced as
such — FDA vetted an instrument nobody picked up. The display collapses
these into a summary line rather than empty blocks.

**Runs live or from cache.** The pipeline is built to run live against
the APIs (ClinicalTrials.gov, RxNav, openFDA, UMLS). For sharing and
demonstration, the COA results are pre-built into a local JSON
(`fda_data/coa_cache.json`) by `build_coa_cache.py`, so queries render
instantly with no network calls. `coa_orchestrator.run_cached` reads the
cache when the query is present and runs live otherwise. There are only
54 COA conditions, so precomputing the entire set is straightforward —
not a workaround for a large dataset, simply a space small enough to
cache completely. The same JSON doubles as a deterministic, offline
test fixture.

### 8c. Index and cache builders

Offline, one-time builds that distill a slow source into a fast local
artifact. Each follows the same pattern the hierarchy indexes use: read
the big source once, write a small JSON, read it instantly thereafter.

- **`build_defining_attributes.py`** → `fda_data/snomed_defined.json`.
  Reads SNOMED's RF2 Relationship file, records which concepts have ≥1
  defining attribute. Feeds the §3 sibling gate.
- **`build_coa_cache.py`** → `fda_data/coa_cache.json`. Runs the COA
  orchestrator for every catalog condition plus a set of demo queries.
  Resumable (writes after each, skips cached), so an interrupted run is
  continued by re-running.

All generated JSON artifacts are gitignored; the builders are the record
of how they were produced.

---

## 9. What the system will not do

- **It will not recommend.** It surfaces what exists and names the
  relation. Whether an instrument fits a trial is a regulatory and
  clinical judgment, and the system has no standing to make it.

- **It will not guess.** When two concepts are both real and no
  authority discriminates, it returns `CONFLICT_DETECTED` and stops.

- **It will not blend sources.** Two routes to a drug stay two routes.
  A confidence score would be a number no auditor could walk back to
  its cause.

- **It will not report absence it did not verify.** A failed lookup and
  a real absence are different states with different names.

- **It will not accept a plausible answer.** SNOMED's ranked hits, a
  regex's grammatical inference, a name that merely looks like an
  instrument's name — all refused. Every one of those produced a wrong
  answer during development, and every one looked correct.

---

## 10. Calibration

Deterministic is not the same as reliable. Deterministic means same
input, same output. Reliable means you actually got the input.

FDA changes the DDT Salesforce structure and the scraper returns fewer
rows — silently. An API call fails and a field is blank —
indistinguishable from a real absence unless instrumented.

Each produces a system that appears to function: deterministic,
reproducible, and wrong.

So every refusal is logged. The near-miss log is not debug output — it
is a calibration instrument. It has overturned three design decisions
during development and confirmed a fourth. Read it before loosening any
rule.

---

## 11. Dependencies

| Source | Access | Cost |
|---|---|---|
| UMLS Metathesaurus (includes SNOMED, MeSH, NCIt, ICD-10-CM, MedDRA) | API key | free (NLM account) |
| ClinicalTrials.gov | public API | free |
| openFDA | API key | free |
| RxNorm / RxClass | public API | free |
| MONDO | bulk download | free |
| Drugs@FDA | bulk download / openFDA | free |

No licensed data and no proprietary vocabularies. Everything here can
be rebuilt from public sources by anyone with the two free API keys.

### Live APIs, not maintained files

The system is built to run on live API calls; it does not depend on
downloading and keeping files up to date. Identity resolution (UMLS),
the hierarchy (SNOMED, MeSH, NCIt, ICD-10-CM, MedDRA — all of which are
UMLS source vocabularies), trials (ClinicalTrials.gov),
drug resolution (RxNav), and approvals (openFDA) are all live external
authorities, maintained by NLM / NIH / FDA, not by this project. When
those authorities update, the system gets the update through the API —
there is nothing local to refresh.

The one exception is MONDO, which is an OBO ontology, not a UMLS source
vocabulary, so it is the single dataset that requires its own periodic
download. Everything else is live.

### Generated local artifacts — a redundant speed cache

The local JSON indexes below add no data. They are cached copies of
UMLS/SNOMED content (and precomputed results) that the APIs already
serve live. They exist for one reason: walking the hierarchy live, per
query, cost ~110 seconds; served from a local index it is ~1 second.
Remove these files and the system still runs — it falls back to the
live UMLS API and is slower. They are a performance choice, not a data
dependency, and each is rebuilt mechanically from a public release
(no hand-curation, no judgment call).

| Artifact | Built by | Caches |
|---|---|---|
| `cui_code_index.json`, `snomed_index.json`, `hierarchy_index.json` | `build_*_index.py` | UMLS/SNOMED hierarchy, to avoid per-query API calls |
| `snomed_defined.json` | `build_defining_attributes.py` | SNOMED defining-attributes (the sibling gate's defined/grouper map) |
| `drug_resolve_cache.json` | `drug_resolver` (on use) | RxNav intervention → ingredient resolutions |
| `coa_cache.json` | `build_coa_cache.py` | pre-built COA-orchestrator results; demo speed + test fixture |