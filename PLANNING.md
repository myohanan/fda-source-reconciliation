# PLANNING.md — FDA Source Reconciliation

Last updated July 12, 2026. Architecture and scope; data findings live
in `fda_data/SPIKE_FINDINGS.md`.

## 0. What this is

A spinoff of the rare-disease endpoint library's canonical-object
engine, pointed at FDA's own fragmented COA / DDT / Drugs@FDA data.

Triggered by an FDA communications response (July 9, 2026) proposing to
"refresh the current webpage" because "the foundation is already
built." That is a front-end answer to a backend problem. The four
resources do not share a key; a website cannot display connections that
do not exist underneath. Confirmed on real data, not inferred.

## 1. Status

**Data foundation: COMPLETE.** Five FDA sources plus four terminology
sources, all on disk, all reproducible from committed scripts.

**condition_resolver: BUILT AND VALIDATED.** 53 of 54 FDA COA
conditions resolved (98%), zero conflicts, one honest NOT_A_CONDITION.
Validated by hand against 100% of the corpus -- not sampled, verified.

**Not yet built:** hierarchy_matcher, coa_lookup, drug_lookup,
orchestrator.

## 2. The user-facing function (one question, one answer)

A developer types a disease. They get:

  - what COAs exist, and their qualification status
  - what drugs are approved
  - what trials exist
  - and, honestly, what does NOT exist

That last one is the product. FDA's current pages cannot say "we looked
and there is nothing," because a catalog can only show its own
contents. Absence is invisible -- indistinguishable from a typo. A
developer searching breast cancer today gets a blank and learns
nothing.

Confirmed on FDA's catalog: no COA for breast cancer, ovarian, cervical,
endometrial, prostate, colorectal, pancreatic, or myocardial infarction.
54 conditions total. Nothing qualified since 2020.

## 3. The architecture: three canonical objects, one resolver

Only ONE object has an identity problem:

  - **Condition** -- NO key anywhere. Must be RESOLVED. This is where
    all the architectural weight lands.
  - **COA** -- identity GIVEN. Key: DDT COA number.
  - **Drug application** -- identity GIVEN. Key: ApplNo.

So: one resolver, several lookups. The lookups are joins on a resolved
key and have no identity problem left to solve. The conductor never
plays violin.

The interesting information lives in the EDGES, and the edges carry a
RELATION, not just a confidence:

    NSCLC is a CHILD of lung cancer
    SCLC is a SIBLING of NSCLC
    "Cancer" is a REMOTE ANCESTOR of both

Three different answers with three different regulatory meanings. A
keyword system has exactly one relation available to it -- "same as" --
and is structurally incapable of expressing any of them.

## 4. condition_resolver: the ladder (sensitive -> specific)

Modeled on sequential testing: a sensitive screen catches everything,
then specific confirmation kills the false positives. You cannot
confirm what you never caught, so the order is not optional.

**1. SENSITIVE SCREEN -- UMLS Metathesaurus, exact search**
   ~200 vocabularies at once, already cross-referenced, CUI as the
   shared key. Miss nothing.

**2. SPECIFIC GATES -- two of them, both deterministic**

   *Semantic type.* Every UMLS concept carries a type the authority
   PUBLISHES. This is the same move as the gene resolver, where
   Orphanet's own disorder_type drives strategy selection: no rule is
   written by hand, a typed field decides.

   It is LOAD-BEARING, not decorative. Searching "itch" returns, ranked:
       C1422257  ITCH gene              -> Gene or Genome        REJECT
       C1141025  ITCH protein, human    -> Protein               REJECT
       C0033774  Pruritus               -> Sign or Symptom       ACCEPT
   Taking the top exact hit resolves "itch" to a GENE.

   *Two-vocabulary minimum.* A concept needs >= 2 independent
   vocabularies calling it by this name. One is not evidence.

**3. DOMAIN AUTHORITY -- ClinicalTrials.gov**
   FDA's COA condition field is written in the language of TRIAL
   ENROLLMENT, because a COA exists to be used in a trial. "Acute
   Bacterial Skin and Skin Structure Infection" is a pathogen class, an
   anatomic site, and an acuity -- not a disease name. No clinical
   vocabulary has a REASON to carry it. The registry does.

**4. CITED EXCEPTION -- FDA guidance**
   A few constructs are defined by a regulatory document, not a
   vocabulary. Named explicitly, with a citation. Currently 1 entry.

**5. HONEST REFUSAL -- NOT_A_CONDITION**
   Nothing in ~200 vocabularies, nothing in the registry, no cited
   guidance. That is a FINDING about FDA's catalog.

## 5. Why no single vocabulary suffices (settled; do not relitigate)

Each vocabulary is COMPLETE for its own question and structurally
incomplete for ours. They do not merely disagree -- they CARVE THE
SPACE DIFFERENTLY, and the carving follows the purpose:

| Vocabulary | Built to answer | Therefore encodes | Systematically misses |
|---|---|---|---|
| ICD-10 | What do we bill for? | Chronicity, laterality, encounter stage | General concepts ("breast cancer" -- too vague to bill) |
| SNOMED | What did the clinician document? | Clinical language | Little; it is the broadest |
| MeSH | What is this paper about? | Publication terms | Clinical phrasing |
| MedDRA | What do we report to the regulator? | FDA's own indication language | Anything outside submission |
| CHV | What does the patient call it? | "itch," "heart attack" | Technical nomenclature |
| Orphanet | What rare diseases exist? | Rare identity | Common disease |
| NCI | What is this cancer? | Tumor taxonomy | Everything else -- its fracture coverage is INCIDENTAL |

That last row is the rule for when a SOLE source counts. A single
vocabulary is authoritative when it OWNS the domain and an artifact
when it is merely passing through. NCI filing "hip fracture" under
PELVIS is not a clinical claim; it is a curation quirk in a vocabulary
that has no business with fractures.

## 6. Hard-won lessons (each cost a wrong answer)

**MONDO is a peer, not a gatekeeper.** An early version required a
MONDO xref before a hit could count. Sarcopenia was matched exactly by
MeSH, SNOMED, AND ICD-10 and returned UNRESOLVED, because a FOURTH
source had a coverage gap. Worse: MONDO cross-references "hip fracture"
to SNOMED's "Fracture of proximal end of femur" -- a NARROWER concept.
Its xrefs are unsafe for identity. MONDO now supplies HIERARCHY ONLY.

**Do not re-derive what the authority already determined.** UMLS's
exact search matches against every ATOM and returns the concept's
PREFERRED NAME -- "itch" returns "Pruritus." A version that re-checked
exactness against that preferred name rejected every correct answer.

**A deterministic rule can still generate an unearned claim.** A regex
decomposed "Acute Bacterial Exacerbation of Chronic Bronchitis IN
PATIENTS WITH COPD" into core + population restriction. But chronic
bronchitis IS a form of COPD -- the "restriction" is the parent
category. And FDA's own SEALD review says the clinical work is done by
BACTERIAL, excluding non-bacterial exacerbations. The regex found
GRAMMAR and generated MEANING. It was deterministic and still wrong --
WORSE for being deterministic, because a reviewer would trust it. The
decomposer was removed. This is the plausible-but-unearned failure
mode, and it does not require a model call to occur.

**Normalization bugs masquerade as vocabulary gaps.** Stripping
apostrophes turned "Alzheimer's Disease" into "alzheimer s disease" and
made four of the most recognizable diseases in medicine unresolvable.
A four-line fix moved resolution from 75% to 89%.

**Asymmetric normalization nearly produced a false finding.** The trial
registry writes "Acute Bacterial Exacerbation of Chronic Bronchitis
(ABECB)." with the abbreviation and a period. Comparing our normalized
string against their raw string reported a false miss.

**A silent path is the dangerous one.** A source that hit but yielded
no CUI vanished with nothing logged. Every refusal is now recorded.

## 7. The near-miss log is a calibration instrument

Not debug output. It has OVERTURNED two design decisions
(MONDO-as-gatekeeper; the regex decomposer) and CONFIRMED one
(exact-match-only). Read it before loosening any rule.

Exact-match-only was settled by evidence, not preference. SNOMED's
rank-1 for "hip fracture" is "Fracture of proximal end of femur" --
narrower, plausible, wrong, and silent. Its rank-1 for "Cancer" is
fine; rank-3 onward is "Malignant neoplasm of stomach... of skin... of
pancreas." SNOMED's ranking optimizes for CLINICAL RETRIEVAL, and does
that job well. It cannot be trusted for identity.

## 8. Thresholds: measured, never guessed

The two-vocabulary minimum was NOT tuned. The corpus was run first with
no rule at all, and every contested case examined:

    Alopecia areata   21 vocabs  vs  1  and 1
    Cancer            22 vocabs  vs  0  (NOTHING calls Neoplasms "cancer")
    Obesity           33 vocabs  vs  1  (an OMIM genetic LOCUS)
    Hip fracture      14 vocabs  vs  1  (NCI filing it under PELVIS)

There is no close case in the corpus. The margins are 14x, 21x, 33x,
and infinite -- so a 2x rule, a 5x rule, and strictly-greater all give
identical answers, and any number picked would be unjustified by the
data.

So the rule is not a margin. It is the SAME EVIDENTIARY STANDARD
already used for endpoints: two independent sources, or it does not
count. If a future query produces contenders at 8 and 7 votes, that is
a REAL ambiguity, it goes to a human, and THAT is when the boundary
gets learned -- from a case that actually has one.

## 9. Generative agency: none

Key joins, API retrieval, typed-field gates, vote counts. Every step
deterministic. Where the data is genuinely ambiguous, the system
surfaces CONFLICT_DETECTED rather than guessing.

This backend is MORE deterministic than the rare-disease pipeline,
which needed bounded generative agency only because PubMed evidence
synthesis requires judgment. Nothing here does. That is worth saying to
FDA plainly: there is essentially no generative judgment in the
reconciliation layer.

**Terminology (deliberate):** these are TOOLS, not agents. An agent
selects its own goals and actions. A tool with bounded generative
agency executes a specified operation within a specified envelope, with
outputs traceable to inputs. Nothing here is an agent. Inherited
filenames say "agent" for historical reasons; the naming is debt, not a
description.

## 10. Calibration is required even in a deterministic system

Deterministic is not the same as reliable. Deterministic means same
input -> same output. Reliable means you actually GOT the input.

The sources are not under our control. FDA changes the DDT Salesforce
structure and the scraper returns fewer rows -- silently. An API call
fails and a field is blank -- indistinguishable from a real absence
unless instrumented. A COA is renumbered and a regex matches nothing,
reporting a clean zero.

Each produces a system that APPEARS to function: deterministic,
reproducible, and wrong.

Two drift types: DETERMINISTIC drift (sources update, outputs change,
and that is CORRECT -- but unmonitored it is indistinguishable from
breakage) and GENERATIVE drift (nearly absent here, per section 9). The
calibration burden is therefore overwhelmingly about source drift and
infrastructure failure.

## 11. Next

1. `hierarchy_matcher` -- MONDO parents/children. Two resolved
   conditions -> EXACT / CHILD / PARENT / SIBLING / ANCESTOR.
2. `coa_lookup`, `drug_lookup` -- joins on the resolved key.
3. `orchestrator` -- assembles. Different pages suppress different
   tools; the gates run on whatever is assembled.
4. Demo: terminal, not a front end. A terminal answers "what is
   actually underneath this?"; a UI invites the question. And a UI is
   the one thing the communications office already believes is the
   problem.

## 12. PARKING LOT

**Guidance-authority document reader.** The guidance table in
`condition_resolver` is currently a HARDCODED lookup with a citation
attached -- honest, but it does not scale. The real version reads the
COA's OWN documents (all 143 are on disk) and extracts the stated
authority. FDA's SEALD review says, in plain text, "as described within
the September 2012 FDA guidance for industry: [title]." That
generalizes; the table does not. Requires the same discipline as
claim_verification: extract what is stated, verify it appears verbatim,
never infer.

**Routing flag.** When nothing resolves, the honest output is not just
NOT_A_CONDITION -- it is "unable to resolve; the answer is likely in
this COA's own documents; recommend human review." A routing decision,
not a resolution.

**COA submission review** (a SECOND, separate tool). Do not let it eat
the prototype. Question library = FDA's own QP template (enumerated
required sections). Corpus = 143 COA PDFs. Ground truth = the 5 "Not
Accepted" letters paired with their LOIs. Honest limits: only 3 FQPs
exist (demonstration set, NOT a calibration set), and unlike the
reviewer tool there is NO registry-equivalent external anchor -- COA
qualification is a judgment, and the reviewer's judgment IS the
standard. So it gets the MECHANICAL PRE-READ, not a discrepancy engine.
Say so.

## 13. Standing cautions

- Ground truth is the repo and the real data. When output does not
  match expectation, the assumption is the likely fault.
- Every prediction made instead of looking has been wrong. Look.
- Do not let the parking lot eat the prototype.
