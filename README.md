# FDA Source Reconciliation

**A user types a disease. What does FDA have for it -- and what does
FDA not have?**

FDA's four public resources for drug development tools do not share a
key. So a website cannot display connections that do not exist
underneath. This is the layer that makes them exist.

**Start here:** `PLANNING.md` (architecture),
`fda_data/SPIKE_FINDINGS.md` (what the data shows), `COA_AXES.md` (a
parked experiment).

---

## The demonstration

    $ python3 reconciliation_orchestrator.py "congestive heart failure"

    Congestive heart failure (C0018802)
      identity: 28 independent vocabularies agreed

    COA: NONE. Checked all 52 distinct conditions in FDA's COA catalog.

    NEARBY: Chronic heart failure is a SIBLING of your condition, and
    FDA has 4 COAs for it, one QUALIFIED. These are DIFFERENT concepts.
    Whether the instrument applies to your population is a regulatory
    judgment -- read its context of use.

    DRUGS: 1,028 applications; 143 corroborated by both routes.

    >>> FDA has approved therapies for this disease and has no
        qualified instrument to measure outcomes in it.

FDA's page returns a blank for this query.

---

## The pipeline

    Step 1   condition_resolver     a NAME -> a settled IDENTITY
    Step 2   coa_lookup             -> FDA's COAs, or an honest none
    Step 2b  hierarchy_matcher      only if Step 2 found NOTHING
    Step 3   drug_lookup            -> approved drugs, two routes
    Step 4   endpoint_search        only if Step 2 found a COA
    Step 5   the finding            assembled, not re-reasoned

**There is no generative step.** Key joins, coded lookups, typed-field
gates, vote counts over declared vocabularies. Every determination is
deterministic and traceable to the authority that made it.

---

## The tools

| Tool | One job |
|---|---|
| `condition_resolver.py` | A disease name -> a settled identity. UMLS (~200 vocabularies), semantic gate, two-vocabulary minimum, consumer-vocabulary discrimination, ClinicalTrials.gov for trial populations, FDA guidance for cited constructs. **53/54 on FDA's catalog.** |
| `coa_lookup.py` | A settled identity -> FDA's COAs, or an honest none. **The empty result is the product.** |
| `hierarchy_matcher.py` | Two identities -> their relation (PARENT / CHILD / SIBLING / DESCENDANT). Six sources; convergence decides. `NO_HIERARCHY` is a reported state, not a silent zero. |
| `drug_lookup.py` | A settled identity -> approved drugs, by two independent routes (RxNorm coded, openFDA label prose), each labeled, never blended. |
| `endpoint_search.py` | An instrument name -> every trial that registered it as an outcome. **Verbatim text, never a boolean.** |
| `endpoint_lookup.py` | A drug -> what its trials measured. |
| `reconciliation_orchestrator.py` | The conductor. Routes sealed outputs; never re-derives. |

---

## Data acquisition (committed; these are the record)

| Script | What it does |
|---|---|
| `normalize_coa_keys.py` | The COA-number bridge. **71/71 submissions, 7/7 qualified match a DDT project.** |
| `download_openfda_indications.py` | Bridges Drugs@FDA (no disease field) to indication text + rxcui, keyed on ApplNo. 12,572 of 29,198. Needs `OPENFDA_API_KEY`. |
| `download_rxnorm_indications.py` | The coded route. rxcui -> MED-RT may_treat -> MeSH. 11,218 of 11,556 rxcuis. |
| `build_mondo_index.py` | MONDO with its full polyhierarchy and 12 vocabularies of xrefs. |
| `build_mesh_index.py` | 5,194 disease descriptors, 59,532 entry terms. |
| `build_icd10_index.py` | 74,260 codes. |
| `extract_coa_compendium.py` | The 2021 Compendium PDF -> 199 rows. |
| `resolve_compendium_drugs.py` | Its hand-typed drugs -> ApplNo + rxcui. 234 OK, 15 flagged. |
| `download_coa_documents.py` | 143 public COA submission and determination PDFs. |
| `download_coa_templates.py` | FDA's qualification templates. |
| `fda_data/download_ddt.py` | The DDT Salesforce scraper. See `DDT_SCRAPER_TODO.md`. |

## Measurement scripts

| Script | What it measured |
|---|---|
| `run_coa_corpus.py` | The resolver against all 54 conditions. |
| `run_coa_usage.py` | All 80 instruments against the trial registry. **50 appear in zero trials.** |
| `measure_hierarchy.py` | Which of six sources can supply a parent, for all 54. |
| `coa_approval_gap.py` | Approvals since FDA's endpoint record froze in 2021. |
| `test_axes_cdisc.py` | The parked axis schema against 252 CDISC instruments. |

---

## Setup

    pip3 install pdfplumber python-dotenv pyflakes pycodestyle

Two API keys, both free, both in `.env` (gitignored):

    OPENFDA_API_KEY=...     # https://open.fda.gov/apis/authentication/
    UMLS_API_KEY=...        # https://uts.nlm.nih.gov/uts/profile

The UMLS key is required. It is the resolver's authority.

## Run order (first time)

    python3 download_openfda_indications.py    # ~2.5 hrs
    python3 download_rxnorm_indications.py     # reads the above
    python3 resolve_compendium_drugs.py        # reads the above
    python3 build_mondo_index.py
    python3 build_mesh_index.py
    python3 build_icd10_index.py
    python3 extract_coa_compendium.py
    python3 download_coa_documents.py
    python3 run_coa_corpus.py                  # resolves the catalog

Then:

    python3 reconciliation_orchestrator.py "any disease"

---

## Data (gitignored -- reproducible from the scripts above)

Everything lives under `fda_data/`. The scripts are the record; the
data is not committed.
