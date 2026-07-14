# SPEC.md — FDA Source Reconciliation

**For engineers. What each tool takes, what it returns, what it
guarantees, and what it refuses to do.**

---

## 0. The contract

Six single-function tools with sealed handoffs. Each does exactly one
thing, emits a sealed result, and never reaches into another's
business.

**No tool re-derives what an earlier tool determined.** The
orchestrator routes; it does not adjudicate. This is not a style
preference — it is what makes every output traceable to the authority
that produced it.

**There is no generative step anywhere in the pipeline.** Key joins,
coded lookups, typed-field gates, vote counts over declared
vocabularies. A reviewer can walk any determination back to its cause.

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
      semantic_types      what KIND of thing this is
      sources             which vocabularies named it
      n_sources           how many
      mondo_id            if MONDO carries it
      hierarchy_available bool
      candidates          on CONFLICT_DETECTED
      near_misses         every refusal, with its reason
    }

**Statuses, and what each MEANS:**

| Status | Meaning |
|---|---|
| `RESOLVED` | One concept survived the gates. |
| `RESOLVED_AS_TRIAL_POPULATION` | No vocabulary carries it; ClinicalTrials.gov registers it. It is an enrollment definition, not a disease entity. |
| `RESOLVED_FROM_MULTINAME` | The field held several names for one disease; all resolved to the same concept. |
| `RESOLVED_BY_GUIDANCE` | Defined by a cited FDA guidance, not by any terminology. |
| `CONFLICT_DETECTED` | Two or more concepts survived and no authority could adjudicate. **A human decides. The tool does not guess.** |
| `NOT_A_CONDITION` | Hits exist but every one failed the semantic gate. The string names a gene, a procedure, a questionnaire, or a chart observation. |
| `UNRESOLVED` | Nothing in ~200 vocabularies, nothing in the registry, no cited guidance. |

**Guarantees:**
- Exact match only. No ranked hits, no fuzzy scoring.
- Every candidate is gated by its **semantic type** — a field the
  authority publishes, not a rule we wrote.
- A concept needs **two independent vocabularies** naming it to be a
  contender. One is not evidence.
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

**The join is on whatever identity the resolver settled on** — a CUI, or
a normalized trial-population name. Not on a CUI alone. An earlier
version joined on CUI only and silently abandoned the seven conditions
that ClinicalTrials.gov had resolved.

**`NO_COA` is a first-class answer, not a failure.** It reads:

    Resolved to C0006142 (Malignant neoplasm of breast). Checked all 52
    distinct conditions in the FDA COA catalog. FDA has no qualified or
    in-process clinical outcome assessment for this condition.

**`CONDITION_UNRESOLVED` is a DIFFERENT fact** and says so:

    This is NOT a statement that FDA has no COA -- it is a statement
    that we could not determine what disease this is.

Those two are indistinguishable from a blank. The distinction is the
whole point.

**Context of use:** the catalog's column is a lossy summary. The KCCQ's
reads "Patients with CHF." Its qualification statement reads "stage C &
D heart failure, NYHA Classes I-IV, HFpEF or HFrEF." **The document
governs.** This tool points at it and does not summarize it.

---

## 3. hierarchy_matcher

**Input:** two CUIs.
**Output:** their relation, per source and converged.

    EXACT | PARENT | CHILD | SIBLING | ANCESTOR | DESCENDANT
    UNRELATED | NO_HIERARCHY

**Six sources are asked** (SNOMED, MeSH, NCIt, ICD-10-CM, MedDRA,
MONDO). **Convergence decides.** One source cannot overrule three.

**`NO_HIERARCHY` is a reported state with its reason.** Seven of FDA's
54 conditions have no parent in ANY source — and they are exactly the
trial populations. **That is a category fact, not a coverage gap.** A
trial enrollment definition has no taxonomic parent because it is not
the kind of thing that has one.

**Refuses to:**
- Report shared REMOTE ancestry as a relation. Every concept shares the
  root. Congestive and chronic heart failure share twenty SNOMED
  ancestors including "Disorder of thorax." That is not a relationship.
- Say an instrument APPLIES. Surfacing a neighbor is navigation, not
  authorization. Whether a COA qualified for chronic heart failure is
  valid in an acute decompensated trial is a **regulatory judgment**,
  and FDA makes it, not this tool.

---

## 4. drug_lookup

**Input:** a sealed condition object.
**Output:** approved drugs, by TWO independent routes.

    ROUTE 1  CODED    ApplNo -> rxcui -> MED-RT may_treat -> MeSH -> CUI
    ROUTE 2  PROSE    ApplNo -> openFDA indications_and_usage -> text

**They are not a primary and a backup. They answer different
questions.**

- **Coded** is fully coded; no text is read. But MED-RT's `may_treat` is
  BROADER than an approved indication — it captures off-label and
  class-level use, and returns artifacts (aripiprazole `may_treat` "Drug
  Hypersensitivity", a contraindication).
- **Prose** is the approved label — the regulatory truth. But it is a
  **string match**, and that is the one place in this system a silent
  false positive can enter.

**Every drug carries which route found it.** The counts are never
merged. Cardiolite — a cardiac imaging agent — matches "breast" in its
label; it appears in the prose-only bucket with its indication text
printed, so a reader can see what it is.

**Agreement is corroboration. Disagreement is a finding.**

---

## 5. endpoint_search

**Input:** an instrument name.
**Output:** every trial that registered it as an outcome measure — with
**the verbatim outcome text.**

**Never a boolean. Never a count alone.** That restraint was earned:

    FDA's qualified asthma COA is the Asthma DAYTIME Symptom Diary
    (6 items, 0-10, C-Path).

    NAVIGATOR -- the pivotal Phase 3 that got Tezspire approved --
    registered "Change from baseline in Asthma Symptom Diary."

    IT IS A DIFFERENT INSTRUMENT. Ten items, scored 0-4, Globe et al
    2015.

    A string matcher called it a hit. It looked like a hit. Nothing
    about the output would have looked broken.

**Reconciliation:** the retrieved count is checked against the
registry's reported total. An incomplete retrieval is an **error**, not
a shrug. If the registry reports no total, completeness cannot be
verified — and that is also not OK.

---

## 6. reconciliation_orchestrator

**Fixed sequence. Sealed handoffs. Degradation, not halt.**

    Step 1   condition_resolver     SEALED IDENTITY
    Step 2   coa_lookup
    Step 2b  hierarchy_matcher      ONLY if Step 2 found nothing
    Step 3   drug_lookup
    Step 4   endpoint_search        ONLY if Step 2 found a COA
    Step 5   the finding            assembled, not re-reasoned

**Step 2b is suppressed when a COA exists.** Ranging outward to offer
alternatives would substitute the system's judgment for FDA's, on
criteria nobody gave it.

**A tool that fails degrades to a sealed UNKNOWN and the pipeline
continues. It does NOT emit a false negative.**

    "We checked and FDA has no COA"     and
    "We could not check"

are completely different facts, and a user cannot tell them apart from
a blank. The schema records which one happened, in `steps` and
`calibration.degraded_steps`.

---

## 7. What the system will NOT do

This section matters more than the others.

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

## 8. Calibration

Deterministic is not the same as reliable. Deterministic means same
input -> same output. **Reliable means you actually GOT the input.**

FDA changes the DDT Salesforce structure and the scraper returns fewer
rows — silently. An API call fails and a field is blank —
indistinguishable from a real absence unless instrumented.

Each produces a system that appears to function: deterministic,
reproducible, and wrong.

So every refusal is logged. The near-miss log is not debug output — it
is an instrument. **It has overturned three design decisions during
development and confirmed a fourth.** Read it before loosening any
rule.

---

## 9. Dependencies

| Source | Access | Cost |
|---|---|---|
| UMLS Metathesaurus | API key | free (NLM account) |
| ClinicalTrials.gov | public API | free |
| openFDA | API key | free |
| RxNorm / RxClass | public API | free |
| MONDO, MeSH, ICD-10-CM | bulk download | free |
| Drugs@FDA | bulk download | free |

**No licensed data. No proprietary vocabularies. Nothing here cannot be
rebuilt from public sources by anyone with the two free API keys.**
