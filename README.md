# FDA Source Reconciliation

**A user types a disease — any way they say it. What does FDA have for
it, and what does FDA not have?**

FDA has four public resources for clinical outcome assessments. Each can
show what it contains. None can show how its contents connect to the
others, because the four do not share a common key. This project is the
layer that builds that key and reconciles them — against each other, and
against the trial and drug-approval data the four never reference.

---

## The four resources — and why a website refresh cannot unify them

The starting point was a proposal to refresh FDA's four public COA
resources into a better web experience. The four:

| Resource | What it holds |
|---|---|
| **DDT portal** (Drug Development Tools) | COA qualification submissions and their status |
| **COA submissions page** | The process view — every COA submitted to the program, at any stage |
| **Program overview PDF** | A static description of the qualification program |
| **COA Compendium** | The outcome view — the catalog of COAs that completed qualification |

The submissions page and the Compendium are two ends of the same
pipeline: the submissions page is what is *in motion* (letter of intent,
in progress, qualified, withdrawn); the Compendium is what has *finished*
qualification.

Each resource can display what it contains. None can display how its
contents connect — to each other, or to a disease as a user would type
it — because **the four do not share a key.** The DDT portal's project
numbers, the Compendium's instrument names, the submissions on the page,
and a disease name are four different identifier spaces. A website
refresh makes each resource easier to read. It cannot surface a
connection that does not exist in the data underneath.

This system is that missing layer. It resolves a disease to a settled
identity that every resource can be joined to, then reconciles the four
against it — and against the trial registry and the drug approvals the
four never reference. The DDT portal's name is the tell: these are
*Drug Development* Tools. A unified view of them has to connect the
outcome-assessment instrument to the drug development it serves — which
is exactly the connection the four disconnected resources cannot
provide, and the one this layer creates.

---

## The demonstration — one instrument, three ways to ask

FDA qualified the NSCLC-SAQ for a precise population: **Non-Small Cell
Lung Carcinoma**. Type that exact name, and you get a direct hit.

    $ python3 coa_orchestrator.py "Non-Small Cell Lung Carcinoma"

    Non-Small Cell Lung Carcinoma (C0007131)
    COA: NSCLC Symptom Assessment Questionnaire (NSCLC-SAQ)  [QUALIFIED]
         from: this condition
         33 trials used it. Approved drugs in those trials include
         pembrolizumab, carboplatin, pemetrexed, cisplatin, docetaxel,
         osimertinib — 15 in all.

But a clinician might not type the exact qualified name. They might just
say **lung carcinoma**, dropping "non-small cell." The system still
lands on the right instrument — now recognizing NSCLC as a more specific
*child* of what was typed.

    $ python3 coa_orchestrator.py "lung carcinoma"

    Carcinoma of lung (C0684249)
    COA: NSCLC-SAQ  [QUALIFIED]
         from: Non-Small Cell Lung Carcinoma (CHILD of your condition)

Or they might type it the way most people would — clinician or patient —
**lung cancer**. Still lands, now through a deeper path.

    $ python3 coa_orchestrator.py "lung cancer"

    Malignant neoplasm of lung (C0242379)
    COA: NSCLC-SAQ  [QUALIFIED]
         from: Non-Small Cell Lung Carcinoma (DESCENDANT of your condition)

**Three ways of asking, one right answer — reached through three
different relationships.** These are not synonyms: "lung cancer," "lung
carcinoma," and "non-small cell lung carcinoma" are distinct concepts at
different levels of clinical precision. The system resolves each to its
real identity and navigates published medical taxonomy to connect them.

---

## What "child" and "descendant" mean — and why this beats a synonym list

The relationship is shown on purpose. In plain terms:

- **This condition** — an exact match. The COA is qualified for precisely
  what you typed.
- **Child** — the COA is qualified for something *one step more specific*
  than what you typed. You asked for "lung carcinoma"; the COA is for
  "non-small cell lung carcinoma," a specific kind of it.
- **Descendant** — the same idea, further down. You asked for "lung
  cancer"; the COA is for a specific type several steps below.

These are **not** the same thing, and the system says so rather than
hiding it. That is the advantage over a synonym list.

Imagine a researcher studying **squamous cell carcinoma of the lung** who
types "lung cancer." The NSCLC-SAQ surfaces — labeled as a *descendant*
relationship, for non-small cell lung carcinoma. The researcher
immediately sees two things: this instrument is *related* to their area,
and it is *not* an exact match for their specific disease. They can then
judge whether it fits — exactly the call a clinical or regulatory expert
should make, not the software.

A synonym list would have failed this researcher one of two ways: it
would have wrongly equated "lung cancer" with a specific instrument, or
it would not have connected them at all. The relationship approach does
neither. It surfaces the connection, names its nature honestly, and
leaves the judgment where it belongs. **It does not punish you for
coming close, and it does not pretend related things are identical.**

---

## Built to scale, with nothing to maintain

This is not built for the few dozen conditions that happen to have a COA
today. It is built for any disease FDA has — or will have — a COA for.
Add a new COA condition tomorrow and it works, with:

- **No synonym list.** There is no table equating "lung cancer" with
  "lung carcinoma" for anyone to write, maintain, or leave incomplete.
  The relationships come from published medical taxonomy.
- **No convened judgment calls.** Nobody has to bring in clinicians to
  decide, case by case, what relates to what. The taxonomy already
  encodes it.
- **No nonsense.** When no authority can tell two concepts apart, the
  system says so and stops, rather than returning a plausible wrong
  answer. It refuses rather than guesses.

It stands on public medical vocabularies maintained by NLM and NIH, so
what has to stay current is maintained by them, not by this project.

---

## The COA-focused view

    resolve the disease
      → does it have its own COA?
      → if not, does a related condition have one? (child / sibling /
        descendant / ancestor)
      → for each COA in the picture: the trials that used it, and the
        approved drugs those trials tested
      → no COA anywhere: say so plainly

Every drug and every trial shown traces to a COA. Where a disease has no
COA and none nearby — a real gap — the system says exactly that, which is
the fact FDA's own page cannot state.

A qualified COA that no trial ever used is surfaced as its own finding:
FDA vetted an instrument nobody picked up. For a demo, results are
pre-built into a local file so they render instantly; there are only 54
COA conditions, so the entire universe fits in a cache.

---

## The tools

Each does exactly one thing, emits a sealed result, and never reaches
into another's business. **There is no generative step anywhere** — key
joins, coded lookups, typed-field gates, votes over declared
vocabularies. Every determination is traceable to the authority that
made it.

| Tool | One job |
|---|---|
| `condition_resolver.py` | A disease name → a settled identity (a CUI). UMLS (~200 vocabularies), semantic gate, two-vocabulary minimum, ClinicalTrials.gov for trial populations. |
| `coa_lookup.py` | A settled identity → FDA's COAs, or an honest none. **The empty result is the product.** |
| `hierarchy_matcher.py` | Two identities → their relation. Six sources; convergence decides. A SNOMED sibling is gated on defining attributes so a real disease-family relation survives and a classification-axis artifact does not. |
| `neighbor_lookup.py` | A settled identity → the catalog conditions structurally related to it, and how. |
| `neighbor_coa_lookup.py` | Those neighbors → each with its COAs attached, verbatim. |
| `drug_lookup.py` | A settled identity → approved drugs, by two independent routes, each labeled, never blended. |
| `drug_resolver.py` | A free-text trial intervention → a canonical RxNorm ingredient. The canonical-object pattern applied to drugs; fragments collapse, combinations stay whole, controls fall out. |
| `coa_drug_link.py` | A COA instrument → the approved drugs whose trials used it. **Co-occurrence only — never an approval-causation claim.** |
| `endpoint_search.py` | An instrument name → every trial that registered it as an outcome. Verbatim text, never a boolean. |
| `coa_orchestrator.py` | The COA-focused view (above). Cache-backed for instant demos. |
| `reconciliation_orchestrator.py` | The expansive everything-view. Routes sealed outputs; never re-derives. |

---

## Setup

    pip3 install pdfplumber python-dotenv pyflakes pycodestyle

Two API keys, both free, both in `.env` (gitignored):

    OPENFDA_API_KEY=...     # https://open.fda.gov/apis/authentication/
    UMLS_API_KEY=...        # https://uts.nlm.nih.gov/uts/profile

The UMLS key is required — it is the resolver's authority. **There is no
Anthropic or other LLM key, because there is no generative step.** The
whole system is deterministic.

## What it stands on

Identity (UMLS, which includes SNOMED, MeSH, NCIt, ICD-10-CM, MedDRA),
trials (ClinicalTrials.gov), drug resolution (RxNav), and approvals
(openFDA) are all live public authorities. The local index files are a
redundant speed cache of that content — pull them and the system still
runs, just slower. MONDO is the one vocabulary not in UMLS and is the
single dataset that needs its own download. Nothing here is licensed or
proprietary; anyone with the two free keys can rebuild all of it.