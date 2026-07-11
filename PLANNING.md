# PLANNING.md — FDA Source Reconciliation

Last updated July 11, 2026. Architecture and scope; findings live in
`fda_data/SPIKE_FINDINGS.md`.

## 0. What this is

A spinoff of the rare-disease endpoint library's canonical-object
reconciliation engine, pointed at FDA's own fragmented COA / DDT /
Drugs@FDA data.

Triggered by an FDA communications response (July 9, 2026) to the
rare-disease proposal, which pointed at existing FDA resources (COA
Compendium, DDT Qualification Project Search, COA Qualification
Submissions) and proposed to "refresh the current webpage" since "the
foundation is already built."

The diagnosis: that is a front-end answer to a backend problem. The
four resources do not share a common key. A refreshed website cannot
display connections that do not exist in the data underneath; someone
would have to maintain every link by hand, forever — which is exactly
how the current state was produced. Confirmed on real data, not
inferred (see SPIKE_FINDINGS §2, §3, §5).

## 1. Status

**Data foundation: COMPLETE.** All sources pulled and structured. One
run still in progress (openFDA indications, full 29,198-application
pull — see SPIKE_FINDINGS §7).

**Code: ported, not yet reconfigured.** The core files at repo root
(`reconciliation_orchestrator.py`, `source_reconciliation_agent.py`,
`record_schema.py`, `config.py`) are the rare-disease files, renamed.
Their docstrings still describe disease resolution. Rewriting them for
the FDA sources IS the next session's work.

## 2. The architecture (settled — transferred, not invented)

The canonical-object pattern from disease/gene resolution maps directly:

| Gene resolution | FDA reconciliation |
|---|---|
| Disease name (ambiguous label) | COA / condition / drug across sources |
| Reconcile Orphanet/OMIM/MONDO/HGNC | Reconcile Drugs@FDA / Compendium / COA submissions / DDT |
| disease_class -> lookup_strategy | source-type -> reconciliation-strategy (clean-key join vs. name match) |
| Canonical Disease Object | Canonical COA / condition / drug record |
| CONFLICT_DETECTED | Sources name the same thing differently |
| source_of_truth governance | Which FDA source is authoritative per field |

**Why this is NOT harder than rare disease** (settled; do not
relitigate): the FDA conditions are common diseases with mature
ontology coverage, abbreviations come pre-embedded in the source
strings ("Chronic Heart Failure (CHF)"), and there are ~51 unique
conditions in the COA submissions. The Krabbe-collision / UBTF /
FOXG1-returning-Rett problems already solved for rare disease were
harder than anything here.

## 3. What transfers from the rare-disease repo

Already built, port with little or no change:
- **`fda_match_util.py`** — the shared deterministic term matcher
  (whole-word boundary for terms <= 4 chars, substring for longer).
  This IS the Drugs@FDA name-matching layer. It was built to stop
  fda_agent and fda_approval_agent from drifting; it is exactly the
  guard needed for short COA abbreviations (CHF, CKD, AOM, CD).
- **`fda_agent.py`** — parses the FDA Surrogate Endpoint Table live,
  with hardcoded fallback and an implausible-parse detector. A sixth
  source, already built, fully deterministic.
- **`fda_approval_agent.py`** — FDA orphan-drug database. Already
  carries the load-failure-vs-genuine-empty discipline (degrades to
  UNKNOWN rather than a false "no approved therapies") — the same
  distinction `download_openfda_indications.py` encodes as
  NOT_FOUND vs. ERROR.
- **`clinicaltrials_agent.py`** — retrieval with pagination, dedupe by
  NCT, and retrieved-vs-reported count reconciliation.

Port with reconfiguration:
- `citation_integrity_agent.py`, `claim_verification_agent.py` — the
  five-verdict discipline (GREEN / RED-no-mention / RED-contradiction /
  YELLOW-unverified, with RED requiring an affirmative negative)
  transfers; the SOURCE changes from PubMed abstract to document
  section.
- `orchestrator.py` — sealed-handoff discipline transfers; the step
  sequence changes entirely.

## 4. Generative agency in this system: almost none

Worth stating plainly, because it is a strength and a selling point.

The reconciliation is: key joins (deterministic), PDF table extraction
(deterministic), API retrieval (deterministic). The one soft spot is
matching indication text to a canonical condition — and the right
answer there is `fda_match_util` plus a controlled vocabulary, with
CONFLICT_DETECTED / HUMAN_REVIEW_REQUIRED where the data is genuinely
ambiguous. NOT a generative call.

So the FDA backend is MORE deterministic than the rare-disease
pipeline, which needed bounded generative agency only because PubMed
evidence synthesis requires judgment. Nothing here does.

**Terminology note (deliberate):** these are TOOLS, not agents. An
agent selects its own goals and actions. A tool with bounded generative
agency executes a specified operation within a specified envelope, with
outputs traceable to inputs. Nothing in this system is an agent. The
inherited filenames say "agent" for historical reasons; the naming is
debt, not a description.

## 5. Why calibration is required even in a deterministic system

Deterministic is not the same as reliable. Deterministic means same
input -> same output. Reliable means you actually GOT the input.

The sources are not under our control and change on their own
schedules:
- An openFDA call fails -> a blank indication field. Is that a drug
  with no indication, or a call that did not go through?
  Indistinguishable unless instrumented. (Hence distinct NOT_FOUND /
  ERROR / HTTP_nnn statuses.)
- FDA changes the DDT Salesforce structure -> the scraper returns fewer
  rows, silently. The reconciliation still "works," it just covers less.
- A COA is renumbered or a page layout shifts -> the regex matches
  nothing and reports a clean zero.

Each of these produces a system that APPEARS to function: deterministic,
reproducible, and wrong.

**Two drift types, both real:**
- *Deterministic drift* — sources update, outputs change, and that is
  CORRECT. New COA qualified, new drug approved. The system SHOULD
  change. But unmonitored, it is indistinguishable from silent
  breakage.
- *Generative drift* — plausible-but-unearned output no source
  supports. Nearly absent here (see §4), because there is nearly no
  generative agency.

So the calibration burden in this system is overwhelmingly about
deterministic drift and infrastructure failure. That is a simpler and
more defensible posture than the rare-disease pipeline, and worth
saying to FDA plainly.

## 6. Demonstration plan

Same coverage-set logic as the Cat 1-4 rare-disease demo diseases.
Resolve real entities from different anchors, chosen to span the
difficulty range:
- **Condition-anchored** — for this disease, what COAs / drugs /
  approvals exist (the empty-cell view)
- **COA-anchored** — for this COA, what conditions and drugs use it,
  what is its qualification status
- **Drug-anchored** — for this approved drug, what COA measured its
  endpoints

At least one case MUST surface a genuine CONFLICT_DETECTED /
no-clean-match. Surfacing the conflict is correct behavior, not a
weakness. The demo shows it; it does not hide it.

Specific entities for these cases: NOT YET SELECTED.

**Demo format: terminal, not a front end.** A terminal demo is more
credible to a technical audience than a UI, because a UI invites "what
is actually underneath this?" and a terminal answers it. A front end is
also the one thing the communications office already believes is the
problem.

## 7. Scope boundary: what is NOT being built here

- **No serving layer.** The rare-disease pipeline rendered static
  documents; it never had to serve data to a front end. A serving layer
  (reconciled model -> queryable API/store) is genuinely new, modest
  (~1 week), and needed for ANY front end. It is NOT needed for a
  backend prototype. Do not let it creep into scope.
- **No front end.** Out of scope. If built later, the tax is the
  learning curve, not the code.

## 8. PARKING LOT: COA submission review (a SECOND, separate tool)

Recorded here so it is not lost. **This is not the prototype. Do not
let it eat the reconciliation work.**

**The idea:** the COA qualification program's bottleneck is throughput —
expert reviewer time — not policy. Published review clocks are LOI 3
months, QP 6 months, FQP 10 months, and the clock does not even START
until a submission is deemed "reviewable" (the completeness assessment,
whose timeline is not specified in the guidance at all). 46.7% of
submissions exceed the published targets. Nothing has been qualified
since 2020.

A completeness assessment is PURE MECHANICAL CHECKING. So is verifying
that cited references exist and support what the submission claims.
That is precisely what `citation_integrity` and `claim_verification`
already do.

**The three pieces are all on disk:**
1. **Question library** — `fda_data/coa_templates/`. The Qualification
   Plan template (fda_147023.pdf) is a fully enumerated numbered
   required-section list: 1.1-1.5 (introduction, concept of interest,
   context of use, COA details, expertise), 3.1-3.8 (literature review,
   expert input, respondent input, concept elicitation, item
   generation, cognitive interviews, item finalization, conceptual
   framework), 4.1-4.2 (study design, inclusion/exclusion, assessment
   timing, sample size and justification, baseline characteristics,
   item-level statistics, dimensionality, item reduction). Each
   numbered subsection is a completeness-check item; present/absent is
   deterministic. The checklist is NOT invented — it is FDA's own
   published template, the COA-domain equivalent of CONSORT.
2. **Corpus** — `fda_data/coa_documents/`, 143 PDFs (26 LOIs, 45
   determination letters, 3 FQPs, 2 Reviews, 1 SEALD Review).
3. **Ground truth** — the 5 "FDA Response (NOT Accepted)" letters,
   paired with their LOIs. FDA's own written reasoning about what was
   inadequate. If the tool, reading an LOI, surfaces what FDA
   independently flagged, that is a VALIDATED demonstration, not merely
   a working one.

**The document-as-canonical-object approach** (worked out in the
FDA-review repo's PLANNING.md §11-12, a separate project): a document
is not a blob to hand an LLM. It is a structured object with role-tagged
regions, and each question has a KNOWN ADDRESS inside it. Methods
answers "what was prespecified." Results answers "what was found."
Discussion is the spin zone. The element taxonomy is finite (printed
statistic / labeled count / axis-read / table-as-image), and the
question set is finite and inherited (CONSORT, PRISMA, STROBE — or here,
FDA's own template). The atomic operation is: read the role-appropriate
section, holding one question, return a structured answer.

**HONEST LIMITS — record these; they are what keep this from being
oversold:**
- **Only 3 FQPs exist.** This is a DEMONSTRATION set, not a CALIBRATION
  set. You can prove the mechanism works on n=1-3 (structure is
  learnable from few instances — that is why canonical objects work).
  You CANNOT estimate a reliability RATE from n=3. Any "the tool
  handles X% of the mechanical review" claim must be calibrated on the
  drug review packages (abundant, public), not COA data.
- **There is NO registry-equivalent external anchor.** The FDA-review
  tool's power comes from ClinicalTrials.gov: timestamped, structured
  prespecification you can check a document against. COA qualification
  has no such thing. "Is this instrument fit for purpose?" is a
  JUDGMENT, and the reviewer's judgment IS the standard. So the
  two-tier split (externally-verifiable vs. internally-attestable)
  collapses toward the judgment tier here.
- Therefore: COA review gets the MECHANICAL PRE-READ, not a discrepancy
  engine. Completeness, citation verification, claim-vs-source
  checking, internal numeric consistency. NOT the scientific judgment.
  That is a weaker claim than the review tool's — and it must be stated
  as such.
- **Only portions of submissions are public.** LOI sections 1-4; QP
  sections 1-2. The full psychometric appendices are not posted.

**Framing, if this is ever offered:** the tool does the clerical
pre-read so scarce reviewer judgment goes to the judgment. Not "AI
speeds up FDA review" — that reads to a reviewer, in a cut-budget
environment, as the justification for the next round of cuts. The
honest claim is a CAPACITY claim (hours come back), not a TIMELINE
claim (review calendars include queue time, information requests,
consultations — automating 200 clerical hours does not compress 10
months proportionally).

## 9. Immediate next steps

1. Finish the openFDA run; record the coverage number in
   SPIKE_FINDINGS §7.
2. Reconfigure the four ported core files for the FDA sources
   (docstrings first — they still describe disease resolution).
3. Port `fda_match_util.py` from the rare-disease repo.
4. Select the demonstration entities (§6).
5. Decide the controlled vocabulary for indication-name normalization
   (MONDO/MeSH). Nothing on disk yet serves this role — it is the one
   genuinely missing artifact for a clean canonical object.

## 10. Standing cautions

- Ground truth is the repo and the real data. When output does not match
  expectation, the assumption is the likely fault, not the machine.
- Architecture is settled and transferred. If code looks inconsistent
  with it, ask whether it is intentional before treating it as a defect.
- Every "general engine" claim is a hypothesis until proven on a SECOND
  domain. This IS the second domain. Building it converts belief to
  demonstrated fact.
- Do not let the parking-lot idea (§8) eat the prototype (§6). The more
  interesting problem is the classic way the shippable one dies.
