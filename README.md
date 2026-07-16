# FDA Source Reconciliation

FDA has four public resources for clinical outcome assessments (COAs).
Each one holds real, valuable information. But they were built
separately and don't share a common identifier, so today it's hard to
move between them or connect them to a disease as someone would actually
search for it. This project builds that connecting layer.

---

## The four resources

The starting point was a proposal to bring FDA's four public COA
resources into one better experience. The four:

| Resource | What it holds |
|---|---|
| **DDT portal** (Drug Development Tools) | COA qualification submissions and their status |
| **COA submissions page** | Every COA submitted to the program, at any stage — the pipeline in motion |
| **Program overview PDF** | A description of the qualification program |
| **COA Compendium** | The COAs that have completed qualification — the finished set |

The submissions page and the Compendium are two ends of one pipeline:
the submissions page shows what's in motion (letter of intent, in
progress, qualified, withdrawn); the Compendium shows what has finished.

Bringing these together is the right goal — they clearly belong
together. The reason it takes more than a redesigned page is that the
four don't share a key: the DDT portal's project numbers, the
Compendium's instrument names, the submissions listing, and a disease
name are four separate identifier spaces. A connection can only be
shown once it exists in the data, so the connecting has to happen
underneath before any front end can present it. That underneath layer
is what this builds.

---

## Tell me about a specific disease

You want to know what COAs FDA has for a disease you care about — and if
it has none, whether anything close does. You type the disease however
you'd naturally say it; you don't have to know the exact term FDA used.

FDA qualified the NSCLC-SAQ for a precise population: **Non-Small Cell
Lung Carcinoma**. Type that exact name and you get a direct hit:

    $ python3 coa_orchestrator.py "Non-Small Cell Lung Carcinoma"

    Non-Small Cell Lung Carcinoma (C0007131)
    COA: NSCLC Symptom Assessment Questionnaire (NSCLC-SAQ)  [QUALIFIED]
         from: this condition
         33 trials used it. Approved drugs in those trials include
         pembrolizumab, carboplatin, pemetrexed, osimertinib — 15 in all.

A clinician might drop "non-small cell" and just type **lung
carcinoma**. It still lands, recognizing NSCLC as a more specific kind
of what was typed:

    $ python3 coa_orchestrator.py "lung carcinoma"

    Carcinoma of lung (C0684249)
    COA: NSCLC-SAQ  [QUALIFIED]
         from: Non-Small Cell Lung Carcinoma (CHILD of your condition)

Or someone might type it the way most people would — **lung cancer**.
Still lands, through a longer path:

    $ python3 coa_orchestrator.py "lung cancer"

    Malignant neoplasm of lung (C0242379)
    COA: NSCLC-SAQ  [QUALIFIED]
         from: Non-Small Cell Lung Carcinoma (DESCENDANT of your condition)

Three ways of asking, one right answer. You don't have to know the exact
term FDA used. The relationship is labeled on purpose — **this
condition**, **child**, **descendant** — so you can see whether the
instrument fits your population and decide for yourself.

It connects those different names through the published medical
vocabularies NLM and NIH already maintain. "Lung cancer," "lung
carcinoma," and "non-small cell lung carcinoma" are the same idea at
different levels of precision, and the taxonomy already knows how they
relate. The benefit to you: no synonym list to build or keep current,
and no need to convene clinicians to decide case by case what relates to
what. It works for any disease with a COA, now or later, and stays
current because those vocabularies are maintained for you.

When a disease genuinely has no COA and nothing close does, it says so
plainly. And a qualified COA that no trial ever used is surfaced too —
an instrument that was vetted but never picked up.

---

## Show me what's actually in the catalog

The other thing you want is a clear picture of the catalog itself: how
many COAs there are, how many were submitted, how many reached the
letter-of-intent stage and went no further, which are qualified and
which weren't accepted, and what exists for a given disease or under a
given instrument name.

The catalog search answers these. It reads both resources — the
submissions pipeline and the finished Compendium — and every query opens
with a count summary before the detail:

    $ python3 list_coas.py

    SUMMARY
      Submissions: 72
           53  Letter of Intent- Accepted
            7  Letter of Intent- Not Accepted
            3  Qualification Plan- Accepted
            ...
      Compendium (completed): 199

So at a glance: 72 COAs submitted, 53 of them still sitting at letter of
intent, and 199 that completed qualification. From there you can narrow:

    $ python3 list_coas.py --search "SDMT"           # one instrument's record
    $ python3 list_coas.py --search "walk"           # every walk-test COA
    $ python3 list_coas.py --stage "letter of intent"
    $ python3 list_coas.py --type PerfO

Search by disease, by instrument name or abbreviation, by qualification
stage, or by COA type — and combine them.

---

## The tools

Each tool does one thing and hands a clean result to the next. There's
no generative step anywhere — every result is a key join, a coded
lookup, or a vote over published vocabularies, traceable back to the
authority that produced it.

The two experiences above:

- **`coa_orchestrator.py`** — "tell me about a specific disease": type a
  disease, get its COAs and the trials and approved drugs connected to
  them. Cache-backed, so it's instant.
- **`list_coas.py`** — "show me what's in the catalog": search both COA
  resources by disease, instrument, stage, or type.

The single-purpose tools they build on:

- **`condition_resolver.py`** — a disease name to a settled identity (a
  CUI), using UMLS (~200 vocabularies) plus ClinicalTrials.gov for trial
  populations.
- **`coa_lookup.py`** — an identity to FDA's COAs for it, or an honest
  none.
- **`hierarchy_matcher.py`** — two identities to how they're related
  (parent, child, sibling, descendant), by agreement across six
  vocabularies.
- **`neighbor_lookup.py`** / **`neighbor_coa_lookup.py`** — the related
  catalog conditions, and their COAs.
- **`drug_lookup.py`** — an identity to approved drugs, by two
  independent routes, each labeled.
- **`drug_resolver.py`** — a free-text trial drug name to a canonical
  RxNorm ingredient.
- **`coa_drug_link.py`** — a COA to the approved drugs whose trials used
  it (co-occurrence, not an approval claim).
- **`endpoint_search.py`** — an instrument name to every trial that
  registered it as an outcome.
- **`reconciliation_orchestrator.py`** — a fuller everything-view that
  also pulls the approved drugs and what their trials measured.
- **`trial_instruments.py`** *(prototype)* and **`group_measures.py`**
  *(utility)* — for a disease's approved drugs, what their trials
  measured, grouped for readability.

---

## Setup

    pip3 install pdfplumber python-dotenv pyflakes pycodestyle

Two API keys, both free, both in `.env` (gitignored):

    OPENFDA_API_KEY=...     # https://open.fda.gov/apis/authentication/
    UMLS_API_KEY=...        # https://uts.nlm.nih.gov/uts/profile

The UMLS key is the resolver's authority. There's no LLM key, because
there's no generative step — the whole system is deterministic.

## What it stands on

Identity (UMLS, which includes SNOMED, MeSH, NCIt, ICD-10-CM, MedDRA),
trials (ClinicalTrials.gov), drug resolution (RxNav), and approvals
(openFDA) are all live public authorities. The local index files are a
speed cache of that same content — remove them and it still runs, just
slower. MONDO is the one vocabulary not in UMLS, so it's the single
dataset that needs its own download. Nothing here is licensed or
proprietary.