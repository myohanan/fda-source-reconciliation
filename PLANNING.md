# PLANNING.md — FDA Source Reconciliation

Last updated July 16, 2026. Architecture and scope; data findings live
in `fda_data/SPIKE_FINDINGS.md`. The parked axis-schema experiment lives
in `COA_AXES.md`.

## 0. What this is

A backend that answers one question: a user types a disease — what does
FDA have for it, and what does FDA not have?

Prompted by an FDA communications exchange (July 9, 2026) about bringing
four public resources into one better experience: the DDT portal, the
COA submissions page, the program overview PDF, and the COA Compendium.

The technical finding: the connections have to be built at the data
layer before any interface can present them. The four resources do not
share a key, so a connection can only be shown once it exists in the
data underneath. Confirmed on real data, not inferred.

## 1. Status: built and working

All tools committed and validated against FDA's own data. Each does one
thing and hands a sealed result to the next.

| Tool | One job | State |
|---|---|---|
| `condition_resolver` | a disease name to a settled identity | 53/54 |
| `coa_lookup` | identity to FDA's COAs, or an honest none | works |
| `hierarchy_matcher` | two identities to their relation | 47/54 have one |
| `neighbor_lookup` | identity to the related catalog conditions, and how | works |
| `neighbor_coa_lookup` | those neighbors to their COAs, attached | works |
| `drug_lookup` | identity to approved drugs, two routes | works |
| `drug_resolver` | a trial's free-text drug string to a canonical ingredient | works |
| `coa_drug_link` | a COA to the approved drugs whose trials used it | works |
| `endpoint_search` | an instrument to the trials that used it | works |
| `list_coas` | search the raw catalog: full list, by disease, instrument, stage, or type | works |
| `coa_orchestrator` | the COA-focused view; cache-backed for demos | works |
| `reconciliation_orchestrator` | the expansive everything-view | works |
| `trial_instruments` | what a disease's approval trials measured, flagged qualified/CDISC/other | prototype |
| `group_measures` | groups a measure list under shared leading words for readability | utility |

There are two orchestrations over the same sealed identity: a tight,
COA-focused view (the demo MVP) and the expansive reconciliation view.
They share every underlying tool and differ only in scope.

## 2. The pipeline

    Step 1   condition_resolver     sealed identity
    Step 2   coa_lookup             COAs, or an honest none
             neighbor_lookup        only if Step 2 found nothing
             neighbor_coa_lookup    only if neighbors were found
    Step 3   drug_lookup            approved drugs, two routes
    Step 4   endpoint_search        only if Step 2 found a COA
    Step 5   the finding            assembled, not re-reasoned

The neighbor search (finding a related catalog condition and attaching
its COAs) is split into two tools, so a failure in one is diagnosable
without reading the other. Both run only when the disease itself has no
COA — ranging outward when a direct answer exists would substitute the
system's judgment for FDA's.

The COA-focused orchestration (`coa_orchestrator`) uses these same tools
in a tighter arrangement: for each COA in the picture — the disease's
own, or a related condition's — it pulls that instrument's trials
(`endpoint_search`) and the approved drugs those trials tested
(`coa_drug_link`). Every drug and trial it shows traces to a COA.

The system has no generative step. It runs on key joins, coded lookups,
typed-field gates, and vote counts over declared vocabularies. Every
determination is deterministic and traceable to the authority that made
it. Where the data is genuinely ambiguous, the system surfaces
CONFLICT_DETECTED and stops rather than guessing. This is a narrower
claim than an evidence-synthesis pipeline could make, and it fits the
domain: source reconciliation is a joining problem, not a judgment one.

The one place free text is read is the openFDA indication prose in Step
3. It is guarded by a word-boundary rule, labeled as text-derived, and
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
right instrument, now via a more-specific child:

    QUERY: "lung carcinoma"

    Carcinoma of lung (C0684249)
    COA: NSCLC-SAQ [QUALIFIED]
         from: Non-Small Cell Lung Carcinoma (CHILD of your condition)

Or they type it the way most people would — clinician or patient. Still
lands, now via a descendant:

    QUERY: "lung cancer"

    Malignant neoplasm of lung (C0242379)
    COA: NSCLC-SAQ [QUALIFIED]
         from: Non-Small Cell Lung Carcinoma (DESCENDANT of your condition)

Three ways of asking, one right answer, reached through three different
relationships. These are distinct concepts at different levels of
precision, not synonyms. The relation is named on purpose: it stays
specific when the user is specific (ask for NSCLC and you are not
redirected to a small-cell instrument) and forgiving when they are not,
leaving the fit judgment to the expert.

## 4. Why the system uses a taxonomy rather than a synonym list

A synonym list is the natural first approach, and for a small, stable
vocabulary it would be reasonable. The reason this system uses published
medical taxonomy instead is that FDA's own data has three properties a
synonym list cannot represent, and the taxonomy handles all three
without a list to maintain.

**Scale.** UMLS carries 539 distinct concepts containing "heart
failure." SNOMED alone has 159; ICD-10 has 36 codes. These are different
diseases, distinguished by acuity (acute / chronic / acute-on-chronic),
mechanism (systolic / diastolic), laterality, and etiology. A synonym
list would have to either enumerate all of them by hand or collapse them
into one bucket, losing the distinctions FDA's data depends on. The
taxonomy already encodes them.

**More than one relation.** A synonym list expresses one relationship:
"same as." FDA's data requires several:

    NSCLC       is a descendant of lung cancer  (SNOMED, MeSH, NCIt agree)
    SCLC        is a sibling of NSCLC
    "cancer"    is a remote ancestor of both
    chronic HF  is a different concept from congestive HF
                (C0264716 vs C0018802 — confirmed at CUI level)

Naming the relationship is what lets the system be forgiving without
being wrong. A synonym list would have to either treat "lung cancer" and
the specific instrument as identical or leave them unconnected; the
taxonomy connects them and labels the connection.

**Absence has no entry.** To answer "there is no COA for breast cancer,"
a keyword system would need breast cancer added as a term pointing at
nothing — and the same for every disease in medicine. Resolving to an
identity and finding no COA answers this for free, for any disease.

The practical payoff: the relationships come from vocabularies NLM and
NIH already maintain, so there is no synonym list to build or keep
current, and no case-by-case clinician review to assemble one.

## 5. The resolver

Modeled on sequential testing: a sensitive screen catches everything,
then specific confirmation removes the false positives. You cannot
confirm what you never caught, so the order matters.

**1. Sensitive screen — UMLS Metathesaurus, exact search.** ~200
vocabularies at once, already cross-referenced, CUI as the shared key.

**2. Specific gates.**

  *Semantic type.* A field the authority publishes — the same move as
  the gene resolver, where Orphanet's own disorder_type drives strategy
  selection. No rule is written by hand; a typed field decides. It does
  real work here. Searching "itch" returns, ranked:

      C1422257  ITCH gene            -> Gene or Genome      reject
      C1141025  ITCH protein, human  -> Protein             reject
      C0033774  Pruritus             -> Sign or Symptom     accept

  Taking the top exact hit alone would resolve "itch" to a gene.

  *Two-vocabulary minimum.* One vocabulary is not enough to count.

**3. Consumer-vocabulary discrimination.** When two concepts both
survive, a vote count cannot adjudicate — breast cancer is 14 vs 3,
diabetes is 6 vs 5, and any margin tuned to separate the first would
silently pick a winner in the second. So the system asks the authority
that owns the question: for a disease name a person would type, that is
MedlinePlus and the Consumer Health Vocabulary (CHV), whose purpose is
mapping lay language to clinical concepts.

    breast cancer  C0006142  Malignant neoplasm of breast
                             [CHV, MEDLINEPLUS]     <- chosen
                   C0678222  Breast Carcinoma  [CHV]
    diabetes       C0011849  Diabetes Mellitus
                             [CHV, MEDLINEPLUS]     <- chosen
                   C0011847  Diabetes  (the taxonomic parent, which
                             includes insipidus — not what a patient
                             saying "diabetes" means)

The source is the signal, not the count.

**4. Domain authority — ClinicalTrials.gov.** FDA's COA condition field
is written in the language of trial enrollment, because a COA exists to
be used in a trial. "Acute Bacterial Skin and Skin Structure Infection"
is a pathogen class, an anatomic site, and an acuity — not a disease
name any clinical vocabulary has reason to carry. The registry does.

**5. Cited exception — FDA guidance.** One construct (ABECB-COPD) is
defined by a September 2012 guidance, not by any terminology. Named
explicitly, with a citation.

**6. Honest refusal — NOT_A_CONDITION.** Nothing in ~200 vocabularies,
nothing in the registry, no cited guidance. A finding about the catalog.

## 6. Why no single vocabulary suffices (settled)

Each vocabulary is complete for its own question and structurally
incomplete for ours. They do not merely disagree — they divide the space
differently, following their purpose.

| Vocabulary | Built to answer | Encodes | Systematically misses |
|---|---|---|---|
| ICD-10 | What do we bill for? | Chronicity, laterality, encounter stage | "breast cancer" — too vague to bill |
| SNOMED | What did the clinician document? | Clinical language | Little; the broadest |
| MeSH | What is this paper about? | Publication terms | Clinical phrasing |
| MedDRA | What do we report to the regulator? | FDA's own indication language | Anything outside submission |
| CHV | What does the patient call it? | "itch," "heart attack" | Technical nomenclature |
| Orphanet | What rare diseases exist? | Rare identity | Common disease |
| NCI | What is this cancer? | Tumor taxonomy | Everything else; its fracture coverage is incidental |

That last row is the rule for when a single source counts: a vocabulary
is authoritative when it owns the domain and an artifact when it is
merely passing through. NCI filing "hip fracture" under pelvis is not a
clinical claim; it is a curation quirk in a vocabulary that has no
business with fractures.

## 7. The hierarchy: measured, then built

A first version was built on SNOMED alone — because it was on hand, not
because it was the right authority — and its gaps were assumed rather
than measured. Coverage across all 54 conditions was then measured:

    SNOMED    47/54  (87%)      MONDO     38/54  (70%)
    MeSH      43/54  (79%)      ICD-10CM  36/54  (66%)
    NCIt      43/54  (79%)      MedDRA    31/54  (57%)

No source covers everything. 19 conditions have a parent in all six; 18
more in five. So every source is asked, and convergence decides the
relation — one source cannot overrule three. (An early ranking rule let
MedDRA's lone sibling beat three sources saying descendant on NSCLC vs
lung cancer. Fixed: vote count first, relation rank only as tiebreak.)

Breadth of sources is the sensitivity arm: asking several independent
taxonomies means a real relationship is unlikely to be missed. Breadth
alone also surfaces false ones (see the false-sibling case in §9).
Specificity comes not from the number of sources but from the gates and
their sequence — the two-vocabulary minimum, the semantic-type gate, the
convergence rule, and the defining-attributes sibling gate. The design
is a hierarchical structure over multiple databases, arranged to capture
sensitivity and specificity in sequence: breadth so nothing is missed,
gates so nothing false gets through.

NO_HIERARCHY is a reported state with its reason. Seven conditions have
no parent in any source — and they are exactly the trial populations
plus the non-condition. That is a category fact, not a coverage gap: a
trial enrollment definition has no taxonomic parent because it is not
the kind of thing that has one.

Shared ancestry is not a relation. Congestive and chronic heart failure
share twenty SNOMED ancestors, including "Disorder of thorax." Reporting
that would be noise dressed as insight.

## 8. Thresholds: measured, not assumed

The two-vocabulary minimum was not tuned. The corpus was run first with
no rule at all, and every contested case examined:

    Alopecia areata   21 vocabs vs 1 and 1
    Cancer            22 vocabs vs 0  (nothing calls Neoplasms "cancer")
    Obesity           33 vocabs vs 1  (an OMIM genetic locus)
    Hip fracture      14 vocabs vs 1  (NCI filing it under pelvis)

No close case existed — margins of 14x, 21x, 33x, and infinite — so any
specific number would be unsupported by the data. The rule is therefore
not a margin at all; it is the same evidentiary standard already used
for endpoints: two independent sources, or it does not count.

## 9. Design evolution driven by data

Each of these changed because a plausible approach produced a wrong
answer on real data. None was designed a priori.

**A shared parent is not a real sibling — use what the source
publishes.** A naive rule ("two conditions share a parent, so they are
siblings") surfaced cystic fibrosis as a sibling of Gaucher disease.
They are not clinically related; what they share is one SNOMED parent,
"Autosomal recessive hereditary disorder" — an inheritance-pattern
grouping, not a disease family. By that logic every recessive disease
would be a sibling of every other. The fix reads SNOMED more carefully
rather than overriding it: SNOMED publishes defining attributes (finding
site, morphology, and so on) that a real disease concept carries and a
pure grouper does not. Heart failure has 3; malignant neoplasm of lung
has 2; "Autosomal recessive hereditary disorder" has 0. A sibling that
rests only on a zero-attribute grouper is not surfaced — which keeps
congestive/chronic heart failure and drops Gaucher/cystic fibrosis. The
sources find the candidate; a categorical gate (present-or-absent, not a
tuned threshold) removes the false one.

**MONDO is a peer, not a gatekeeper.** Requiring a MONDO xref before a
hit could count returned UNRESOLVED for Sarcopenia — matched exactly by
MeSH, SNOMED, and ICD-10 — because a fourth source had a coverage gap.
MONDO also cross-references "hip fracture" to SNOMED's "Fracture of
proximal end of femur," a narrower concept, so its xrefs are unsafe for
identity; and its `xref_mesh` is empty for breast cancer, which silently
returned zero drugs for the most common cancer in American women. The
resolver asks UMLS directly, since UMLS is the metathesaurus.

**Do not re-derive what the authority already determined.** UMLS's exact
search matches every atom and returns the concept's preferred name —
"itch" returns "Pruritus." A version that re-checked exactness against
that preferred name rejected every correct answer.

**A deterministic rule can still generate an unearned claim.** A regex
decomposed "Acute Bacterial Exacerbation of Chronic Bronchitis in
patients with COPD" into core plus population restriction. But chronic
bronchitis is a form of COPD — the "restriction" is the parent category.
FDA's own SEALD review says the clinical work is done by "bacterial,"
excluding non-bacterial exacerbations. The regex found grammar and
generated meaning; it was deterministic and still wrong, and worse for
being deterministic because a reviewer would trust it. The decomposer
was removed and replaced with a citation.

**Instrument names are not instrument identity.** FDA's qualified asthma
COA is the Asthma Daytime Symptom Diary (6 items, 0-10, C-Path). The
pivotal trial that got Tezspire approved registered "Asthma Symptom
Diary" — a different instrument (10 items, 0-4, Globe et al 2015). A
string matcher called it a hit, and nothing about the output would have
looked broken. So `endpoint_search` returns verbatim text, never a
boolean.

**Normalization bugs masquerade as vocabulary gaps.** Stripping
apostrophes made Alzheimer's, Crohn's, Huntington's, and Parkinson's
unresolvable. A four-line fix moved resolution from 75% to 89%.

**A silent path is the dangerous one.** A source that hit but yielded no
CUI vanished with nothing logged. Every refusal is now recorded.

## 10. The near-miss log is a calibration instrument

Not debug output. It has overturned three design decisions
(MONDO-as-gatekeeper, the regex decomposer, SNOMED-only hierarchy) and
confirmed one (exact-match-only). Read it before loosening any rule.

## 11. Calibration is required even in a deterministic system

Deterministic is not the same as reliable. Deterministic means same
input, same output. Reliable means you actually got the input.

FDA changes the DDT Salesforce structure and the scraper returns fewer
rows, silently. An API call fails and a field is blank, indistinguishable
from a real absence unless instrumented. A COA is renumbered and a regex
matches nothing, reporting a clean zero. Each produces a system that
appears to function — deterministic, reproducible, and wrong.

So a tool that fails degrades to a sealed UNKNOWN and the pipeline
continues; it does not emit a false negative. "We checked and FDA has no
COA" and "we could not check" are different facts, and a user cannot
tell them apart from a blank.

## 12. Next

Done since the last revision:
- SPEC.md, the engineer-facing tool contracts.
- The COA-focused orchestrator with its instant-demo cache.
- The drug-resolution and COA-to-drug tools; the defining-attributes
  sibling gate.
- The full reconciliation orchestrator, now including what a disease's
  approval trials measured.
- `list_coas`, the catalog search. This delivered two of the planned
  doors at once: the full list ("show me everything") and COA-name /
  abbreviation search ("type SDMT, get its record"), plus filtering by
  stage and type. No separate COA-name tool was needed.

Remaining:

1. **Related COAs.** From a COA, walk to its disease and out to related
   conditions' COAs. Honestly framed: COAs have no taxonomy of their
   own, so "related COAs" means "COAs for related conditions," routed
   through the disease layer already built — not a COA taxonomy invented
   here. Optional; lower priority than the doors already delivered.
2. **`trial_instruments` maturation.** The prototype classifies trial
   outcome measures against qualified COAs and CDISC. Making the CDISC
   classification reliable is a real instrument-reconciliation effort
   (trial phrasing vs. CDISC's canonical names), not tuning. Carried as
   a prototype; the empirical finding it produced was verified manually.
3. **The one-pager** — distilled from everything above.

## 13. Parking lot

**Guidance-authority document reader.** The guidance table is a
hardcoded lookup with a citation attached — honest, but it does not
scale. The real version reads the COA's own documents (all 143 are on
disk) and extracts the stated authority. FDA's SEALD review says, in
plain text, "as described within the September 2012 FDA guidance for
industry: [title]." That generalizes; the table does not.

**A "recommend COA review" routing flag.** When nothing resolves, the
honest output is not just NOT_A_CONDITION — it is "unable to resolve; the
answer is likely in this COA's own documents; recommend human review." A
routing decision, not a resolution.

**The axis schema** (`COA_AXES.md`). A LOINC-style decomposition that
discriminates instruments a name-match confuses. Structure validated
across 252 CDISC instruments; the rest unproven. Worth revisiting with
better data.

**COA submission review** (a second, separate tool). Do not let it eat
the prototype. Question library = FDA's own QP template. Corpus = 143
COA PDFs. Ground truth = the 5 "Not Accepted" letters paired with their
LOIs. Honest limits: only 3 FQPs exist (a demonstration set, not a
calibration set), and unlike the reviewer tool there is no
registry-equivalent external anchor — COA qualification is a judgment,
and the reviewer's judgment is the standard. So it gets the mechanical
pre-read, not a discrepancy engine. Say so.

## 14. Standing cautions

- Ground truth is the repo and the real data. When output does not match
  expectation, the assumption is the likely fault.
- Every prediction made instead of a measurement has been wrong. This
  happened five times. Look first.
- Do not let the parking lot eat the prototype.