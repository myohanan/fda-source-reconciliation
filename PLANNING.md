# PLANNING.md — FDA Source Reconciliation

Last updated July 16, 2026. Architecture and scope; data findings live
in `fda_data/SPIKE_FINDINGS.md`. The parked axis-schema experiment lives
in `COA_AXES.md`.

## 0. What this is

A backend that answers one question: **a user types a disease — what
does FDA have for it, and what does FDA not have?**

Triggered by an FDA communications response (July 9, 2026) proposing to
"refresh the current webpage resources" because "the foundation is
already built," citing four resources: the DDT portal, the COA
submissions page, the program overview PDF, and the COA Compendium.

The diagnosis: that is a front-end answer to a backend problem. The four
resources do not share a key, and a website cannot display connections
that do not exist underneath. Confirmed on real data, not inferred.

## 1. Status: BUILT AND WORKING

All tools committed and validated against FDA's own data. Each does one
thing and hands a sealed result to the next.

| Tool | One job | State |
|---|---|---|
| `condition_resolver` | a disease NAME -> a settled IDENTITY | 53/54 |
| `coa_lookup` | identity -> FDA's COAs, or an honest none | works |
| `hierarchy_matcher` | two identities -> their RELATION | 47/54 have one |
| `neighbor_lookup` | identity -> the related catalog conditions, and how | works |
| `neighbor_coa_lookup` | those neighbors -> their COAs, attached | works |
| `drug_lookup` | identity -> approved drugs, two routes | works |
| `drug_resolver` | a trial's free-text drug string -> a canonical ingredient | works |
| `coa_drug_link` | a COA -> the approved drugs whose trials used it | works |
| `endpoint_search` | an instrument -> the trials that used it | works |
| `coa_orchestrator` | the COA-focused view; cache-backed for demos | works |
| `reconciliation_orchestrator` | the expansive everything-view | works |

The system now has TWO orchestrations over the same sealed identity: a
tight, COA-focused view (the demo MVP) and the expansive reconciliation
view. They share every underlying tool and differ only in scope.

## 2. The pipeline

    Step 1   condition_resolver     SEALED IDENTITY
    Step 2   coa_lookup             COAs, or an honest none
             neighbor_lookup        only if Step 2 found NOTHING
             neighbor_coa_lookup    only if neighbors were found
    Step 3   drug_lookup            approved drugs, two routes
    Step 4   endpoint_search        only if Step 2 found a COA
    Step 5   the finding            assembled, not re-reasoned

The neighbor search (finding a RELATED catalog condition, and attaching
its COAs) is split into two tools, so a failure in one is diagnosable
without reading the other. Both run only when the disease itself has no
COA — ranging outward when a direct answer exists would substitute the
system's judgment for FDA's.

The COA-focused orchestration (`coa_orchestrator`) uses these same tools
in a tighter arrangement: for each COA in the picture — the disease's
own, or a related condition's — it pulls that instrument's trials
(`endpoint_search`) and the approved drugs those trials tested
(`coa_drug_link`). Every drug and trial it shows traces to a COA.

**There is no generative step. Not one.** Key joins, coded lookups,
typed-field gates, vote counts over declared vocabularies. Every
determination is deterministic and traceable to the authority that made
it. Where the data is genuinely ambiguous, the system surfaces
CONFLICT_DETECTED and stops — it does not guess.

That is a stronger claim than the rare-disease pipeline can make, and it
is the right one for this domain: PubMed evidence synthesis requires
judgment; source reconciliation does not.

The ONE place free text is read is the openFDA indication prose in Step
3. It is guarded by a word-boundary rule, LABELED as text-derived, and
never merged with the coded count — which is how the Cardiolite false
positive (a cardiac imaging agent matching "breast") stays visible
instead of silently inflating a number.

## 3. The demonstration — one instrument, three ways to ask

FDA qualified the NSCLC-SAQ for a precise population: Non-Small Cell
Lung Carcinoma. Typed exactly, it is a direct hit:

    QUERY: "Non-Small Cell Lung Carcinoma"

    Non-Small Cell Lung Carcinoma (C0007131)
    COA: NSCLC Symptom Assessment Questionnaire (NSCLC-SAQ) [QUALIFIED]
         from: this condition
         33 trials used it; approved drugs in those trials include
         pembrolizumab, carboplatin, pemetrexed, osimertinib — 15 in all.

A clinician might drop "non-small cell." The system still lands on the
right instrument, now via a more-specific CHILD:

    QUERY: "lung carcinoma"

    Carcinoma of lung (C0684249)
    COA: NSCLC-SAQ [QUALIFIED]
         from: Non-Small Cell Lung Carcinoma (CHILD of your condition)

Or they type it the way most people would — clinician or patient. Still
lands, now via a DESCENDANT:

    QUERY: "lung cancer"

    Malignant neoplasm of lung (C0242379)
    COA: NSCLC-SAQ [QUALIFIED]
         from: Non-Small Cell Lung Carcinoma (DESCENDANT of your condition)

Three ways of asking, one right answer, reached through three different
RELATIONSHIPS. These are not synonyms — they are distinct concepts at
different levels of precision. The relation is named on purpose: it is
specific when the user is specific (ask for NSCLC and you are not
misdirected to a small-cell instrument) and forgiving when they are not.
A synonym list would either collapse the distinction or miss the
connection; this preserves it and leaves the judgment to the expert.

FDA's page today does none of this.

## 4. Why a synonym list cannot do this

**Scale.** UMLS carries 539 distinct concepts containing "heart
failure." SNOMED alone has 159; ICD-10 has 36 codes. They are not
synonyms — they are different diseases, crossed on acuity (acute /
chronic / acute-on-chronic), mechanism (systolic / diastolic),
laterality, and etiology. A list would flatten all 539 into one bucket.
That is not compression; it is destruction.

**One relation.** A synonym list can say "same as." FDA's own data
requires at least four:

    NSCLC       is a DESCENDANT of lung cancer  (SNOMED, MeSH, NCIt agree)
    SCLC        is a SIBLING of NSCLC
    "Cancer"    is a REMOTE ANCESTOR of both
    chronic HF  is a DIFFERENT CONCEPT from congestive HF
                (C0264716 vs C0018802 — confirmed at CUI level)

**Absence has no entry.** To say "there is no COA for breast cancer,"
you would have to add breast cancer as a keyword pointing at NOTHING —
and then do that for every disease in medicine. Resolution gets it free.

**And it fails in both directions, which is not a tuning problem.** A
loose keyword system returns hundreds of irrelevant results; a tight one
silently misses conditions it actually covers. Both failures have been
observed in production at major clinical-content companies. The dial is
measuring string proximity; the thing that needs measuring is RELATION.
No setting converts one into the other.

## 5. The resolver: sensitive -> specific

Modeled on sequential testing. A sensitive screen catches everything,
then specific confirmation kills the false positives. You cannot confirm
what you never caught, so the order is not optional.

**1. SENSITIVE SCREEN — UMLS Metathesaurus, exact search.** ~200
vocabularies at once, already cross-referenced, CUI as the shared key.

**2. SPECIFIC GATES.**

  *Semantic type.* A field the authority PUBLISHES — the same move as
  the gene resolver, where Orphanet's own disorder_type drives strategy
  selection. No rule is written by hand; a typed field decides.

  It is LOAD-BEARING. Searching "itch" returns, ranked:
      C1422257  ITCH gene            -> Gene or Genome      REJECT
      C1141025  ITCH protein, human  -> Protein             REJECT
      C0033774  Pruritus             -> Sign or Symptom     ACCEPT
  Taking the top exact hit resolves "itch" to a GENE.

  *Two-vocabulary minimum.* One vocabulary is not evidence.

**3. CONSUMER-VOCABULARY DISCRIMINATION.** When two concepts both
survive, a vote count cannot adjudicate — breast cancer is 14 vs 3,
diabetes is 6 vs 5, and any margin tuned to separate the first would
silently pick a winner in the second.

So ask the authority that owns the question. For a disease name a person
would type, that is MedlinePlus and CHV — the Consumer Health
Vocabulary — whose entire purpose is mapping lay language to clinical
concepts.

    breast cancer  C0006142  Malignant neoplasm of breast
                             [CHV, MEDLINEPLUS]     <- chosen
                   C0678222  Breast Carcinoma  [CHV]
    diabetes       C0011849  Diabetes Mellitus
                             [CHV, MEDLINEPLUS]     <- chosen
                   C0011847  Diabetes  (the taxonomic parent, which
                             includes INSIPIDUS — and no patient saying
                             "diabetes" means that)

The counts are not the signal. The SOURCE is.

**4. DOMAIN AUTHORITY — ClinicalTrials.gov.** FDA's COA condition field
is written in the language of TRIAL ENROLLMENT, because a COA exists to
be used in a trial. "Acute Bacterial Skin and Skin Structure Infection"
is a pathogen class, an anatomic site, and an acuity — not a disease
name. No clinical vocabulary has a REASON to carry it. The registry
does.

**5. CITED EXCEPTION — FDA guidance.** One construct (ABECB-COPD) is
defined by a September 2012 guidance, not by any terminology. Named
explicitly, with a citation.

**6. HONEST REFUSAL — NOT_A_CONDITION.** Nothing in ~200 vocabularies,
nothing in the registry, no cited guidance. A finding about the catalog.

## 6. Why no single vocabulary suffices (settled)

Each is COMPLETE for its own question and structurally incomplete for
ours. They do not merely disagree — they CARVE THE SPACE DIFFERENTLY,
and the carving follows the purpose.

| Vocabulary | Built to answer | Encodes | Systematically misses |
|---|---|---|---|
| ICD-10 | What do we bill for? | Chronicity, laterality, encounter stage | "breast cancer" — too vague to bill |
| SNOMED | What did the clinician document? | Clinical language | Little; the broadest |
| MeSH | What is this paper about? | Publication terms | Clinical phrasing |
| MedDRA | What do we report to the regulator? | FDA's own indication language | Anything outside submission |
| CHV | What does the patient call it? | "itch," "heart attack" | Technical nomenclature |
| Orphanet | What rare diseases exist? | Rare identity | Common disease |
| NCI | What is this cancer? | Tumor taxonomy | Everything else — its fracture coverage is INCIDENTAL |

That last row is the rule for when a SOLE source counts. A single
vocabulary is authoritative when it OWNS the domain and an artifact when
it is merely passing through. NCI filing "hip fracture" under PELVIS is
not a clinical claim; it is a curation quirk in a vocabulary that has no
business with fractures.

## 7. The hierarchy: measured, then built

A first version was built on SNOMED alone — not because SNOMED was the
right authority, but because it was on hand — and the gaps were defended
rather than measured. That was wrong.

Coverage across all 54 conditions was then MEASURED:

    SNOMED    47/54  (87%)      MONDO     38/54  (70%)
    MeSH      43/54  (79%)      ICD-10CM  36/54  (66%)
    NCIt      43/54  (79%)      MedDRA    31/54  (57%)

No source covers everything. 19 conditions have a parent in ALL SIX; 18
more in five. So every source is asked, and **convergence decides the
relation** — one source cannot overrule three. (An early ranking rule
let MedDRA's lone SIBLING beat three sources saying DESCENDANT on NSCLC
vs lung cancer. Fixed: vote count first, relation rank only as
tiebreak.)

**The breadth of sources is the SENSITIVITY arm — nothing more.** Asking
several independent taxonomies means a real relationship is unlikely to
be missed. But breadth alone also surfaces false ones (see the
false-sibling case in §9). SPECIFICITY does not come from the number of
sources; it comes from the gates and the way they are sequenced in the
orchestration — the two-vocabulary minimum, the semantic-type gate, the
convergence rule, and the defining-attributes sibling gate. The whole
design is a hierarchical structure over multiple databases, arranged to
capture sensitivity and specificity in sequence: breadth so nothing is
missed, gates so nothing false gets through.

**NO_HIERARCHY is a reported state with its reason.** Seven conditions
have no parent in ANY source — and they are exactly the trial
populations plus the non-condition. **That is a CATEGORY FACT, not a
coverage gap.** A trial enrollment definition has no taxonomic parent
because it is not the kind of thing that has one.

**Shared ancestry is not a relation.** Congestive and chronic heart
failure share twenty SNOMED ancestors, including "Disorder of thorax."
Reporting that would be noise dressed as insight.

## 8. Thresholds: measured, never guessed

The two-vocabulary minimum was NOT tuned. The corpus was run first with
no rule at all, and every contested case examined:

    Alopecia areata   21 vocabs vs 1 and 1
    Cancer            22 vocabs vs 0  (NOTHING calls Neoplasms "cancer")
    Obesity           33 vocabs vs 1  (an OMIM genetic LOCUS)
    Hip fracture      14 vocabs vs 1  (NCI filing it under PELVIS)

No close case existed. Margins of 14x, 21x, 33x, and infinite — so any
number picked would be unjustified by the data. The rule is therefore
not a margin at all: it is the SAME evidentiary standard already used
for endpoints. Two independent sources, or it does not count.

## 9. Design evolution driven by data

Each of these changed because a plausible approach produced a wrong
answer on real data. None was designed a priori.

**A shared parent is not a real sibling — work with what the source
publishes.** A naive rule ("two conditions share a parent, so they are
siblings") surfaced cystic fibrosis as a sibling of Gaucher disease.
They are not clinically related; what they share is one SNOMED parent,
"Autosomal recessive hereditary disorder" — an inheritance-pattern
grouping, not a disease family. By that logic every recessive disease
would be a sibling of every other. The fix is not to override SNOMED but
to read it more carefully: SNOMED publishes DEFINING ATTRIBUTES (finding
site, morphology, and so on) that a real disease concept carries and a
pure grouper does not. Heart failure has 3; malignant neoplasm of lung
has 2; "Autosomal recessive hereditary disorder" has 0. So a sibling
that rests only on a zero-attribute grouper is not surfaced — which
keeps congestive/chronic heart failure and drops Gaucher/cystic
fibrosis. This is the SPECIFICITY arm doing its job: the sources found
the candidate, a categorical gate (present-or-absent, not a tuned
threshold) removed the false one. You do not get to redesign SNOMED; you
use what it already publishes.

**MONDO is a peer, not a gatekeeper.** Requiring a MONDO xref before a
hit could count returned UNRESOLVED for Sarcopenia — matched exactly by
MeSH, SNOMED, AND ICD-10 — because a fourth source had a coverage gap.
Worse: MONDO cross-references "hip fracture" to SNOMED's "Fracture of
proximal end of femur," a NARROWER concept. Its xrefs are unsafe for
identity. And its `xref_mesh` is EMPTY for breast cancer, which silently
returned ZERO drugs for the most common cancer in American women. **Ask
UMLS directly. It IS the metathesaurus.**

**Do not re-derive what the authority already determined.** UMLS's exact
search matches every ATOM and returns the concept's PREFERRED NAME —
"itch" returns "Pruritus." A version that re-checked exactness against
that name rejected every correct answer.

**A deterministic rule can generate an unearned claim.** A regex
decomposed "Acute Bacterial Exacerbation of Chronic Bronchitis IN
PATIENTS WITH COPD" into core + population restriction. But chronic
bronchitis IS a form of COPD — the "restriction" is the parent category.
FDA's own SEALD review says the clinical work is done by BACTERIAL,
excluding non-bacterial exacerbations. **The regex found GRAMMAR and
generated MEANING. It was deterministic and still wrong — WORSE for
being deterministic, because a reviewer would trust it.** The decomposer
was removed and replaced with a citation.

**Instrument names are not instrument identity.** FDA's qualified asthma
COA is the Asthma DAYTIME Symptom Diary (6 items, 0-10, C-Path). The
pivotal trial that got Tezspire approved registered "Asthma Symptom
Diary" — a DIFFERENT instrument (10 items, 0-4, Globe et al 2015). A
string matcher called it a hit. **Nothing about the output would have
looked broken.** So `endpoint_search` returns VERBATIM text, never a
boolean.

**Normalization bugs masquerade as vocabulary gaps.** Stripping
apostrophes made Alzheimer's, Crohn's, Huntington's, and Parkinson's
unresolvable. A four-line fix moved resolution from 75% to 89%.

**A silent path is the dangerous one.** A source that hit but yielded no
CUI vanished with nothing logged. Every refusal is now recorded.

## 10. The near-miss log is a calibration instrument

Not debug output. It has OVERTURNED three design decisions
(MONDO-as-gatekeeper, the regex decomposer, SNOMED-only hierarchy) and
CONFIRMED one (exact-match-only). Read it before loosening any rule.

## 11. Calibration is required even in a deterministic system

Deterministic is not the same as reliable. Deterministic means same
input -> same output. Reliable means you actually GOT the input.

FDA changes the DDT Salesforce structure and the scraper returns fewer
rows — silently. An API call fails and a field is blank —
indistinguishable from a real absence unless instrumented. A COA is
renumbered and a regex matches nothing, reporting a clean zero.

Each produces a system that APPEARS to function: deterministic,
reproducible, and wrong.

So: a tool that fails degrades to a sealed UNKNOWN and the pipeline
continues. It does NOT emit a false negative. "We checked and FDA has no
COA" and "we could not check" are completely different facts, and a user
cannot tell them apart from a blank.

## 12. Next

Done since the last revision: SPEC.md (the engineer-facing tool
contracts), the COA-focused orchestrator with its instant-demo cache,
the drug-resolution and COA-to-drug tools, and the defining-attributes
sibling gate. Remaining:

1. **Finish the full reconciliation orchestrator** — the expansive
   everything-view, polished to match the COA orchestrator's output
   quality.
2. **Additional entry points (doors), all routing through the same
   identity engine.** The system currently answers "disease -> COAs."
   The same machinery answers other questions, each buildable without
   new relationship logic:
   - **COA-name / abbreviation search.** Type an instrument ("KCCQ") and
     get its record — what it is qualified for, its context of use, its
     trials, its status. The inverse of the disease search.
   - **The full list.** Show every COA in the catalog. Trivial — the
     catalog is already loaded — and the first thing a reviewer will
     ask for.
   - **Related COAs.** From a COA, walk to its disease and out to
     related conditions' COAs. Note honestly: COAs have no taxonomy of
     their own, so "related COAs" means "COAs for related conditions,"
     routed through the disease layer already built — not a COA
     taxonomy invented here.
3. **The one-pager** — last, distilled from everything above.

## 13. PARKING LOT

**Guidance-authority document reader.** The guidance table is a
HARDCODED lookup with a citation attached — honest, but it does not
scale. The real version reads the COA's OWN documents (all 143 are on
disk) and extracts the stated authority. FDA's SEALD review says, in
plain text, "as described within the September 2012 FDA guidance for
industry: [title]." That generalizes; the table does not.

**A "recommend COA review" routing flag.** When nothing resolves, the
honest output is not just NOT_A_CONDITION — it is "unable to resolve;
the answer is likely in this COA's own documents; recommend human
review." A routing decision, not a resolution.

**The axis schema** (`COA_AXES.md`). A LOINC-style decomposition that
discriminates instruments a name-match confuses. STRUCTURE validated
across 252 CDISC instruments; the rest unproven. Worth revisiting with
better data.

**COA submission review** (a SECOND, separate tool). Do not let it eat
the prototype. Question library = FDA's own QP template. Corpus = 143
COA PDFs. Ground truth = the 5 "Not Accepted" letters paired with their
LOIs. Honest limits: only 3 FQPs exist (a demonstration set, NOT a
calibration set), and unlike the reviewer tool there is NO
registry-equivalent external anchor — COA qualification is a judgment,
and the reviewer's judgment IS the standard. So it gets the MECHANICAL
PRE-READ, not a discrepancy engine. Say so.

## 14. Standing cautions

- Ground truth is the repo and the real data. When output does not match
  expectation, the assumption is the likely fault.
- **Every prediction made instead of a measurement has been wrong.**
  This happened five times. Look first.
- Do not let the parking lot eat the prototype.