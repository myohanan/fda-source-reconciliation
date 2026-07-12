# FDA Source Reconciliation

Reconciles FDA's fragmented COA / DDT / Drugs@FDA data into canonical
records. A spinoff of the rare-disease endpoint library's
canonical-object engine, pointed at FDA's own sources.

**Start here:** `PLANNING.md` (architecture, scope, next steps) and
`fda_data/SPIKE_FINDINGS.md` (what the data actually shows).

## The problem, in one line

The four FDA resources do not share a common key, so a website refresh
cannot display connections that do not exist underneath.

## Three routes to the same canonical object

    route 1  ApplNo -> openFDA indication text -> MONDO
    route 2  ApplNo -> rxcui -> RxNorm may_treat -> MeSH -> MONDO
    truth    the COA Compendium's hand-built disease-drug links,
             resolved to the same ApplNo

Agreement is corroboration. Disagreement is a finding, not an error.

## Scripts (committed; these are the record)

| Script | What it does |
|---|---|
| `normalize_coa_keys.py` | The COA-number bridge. Normalizes `DDT-COA-000112` / `DDT COA #000112` to a canonical 6-digit key and reports overlap across the three COA sources. **The proven join: 71/71 submissions, 7/7 qualified.** |
| `download_openfda_indications.py` | Bridges Drugs@FDA (no disease field) to indication text + rxcui/unii/pharm_class, keyed on ApplNo. 12,572 of 29,198 matched. Needs `OPENFDA_API_KEY` in `.env`. |
| `download_rxnorm_indications.py` | The coded route. rxcui -> MED-RT `may_treat` -> MeSH-coded diseases. 11,218 of 11,556 rxcuis carry a coded indication. Run AFTER the openFDA pull. |
| `build_mondo_index.py` | The resolution source. Downloads MONDO and builds an index with the full is_a hierarchy (10,657 classes are polyhierarchical) and xrefs to 12 vocabularies. Keeps the raw ontology. |
| `extract_coa_compendium.py` | Extracts the COA Compendium PDF to `coa_compendium.csv` (199 rows) via pdfplumber. |
| `resolve_compendium_drugs.py` | Connects the validation set to the pipeline. Parses `Brilinta (ticagrelor) July 20, 2011` -> brand/generic/date, resolves to ApplNo + rxcui, and corroborates via the generic name. 234 OK, 15 flagged GENERIC_MISMATCH. Run AFTER the openFDA pull. |
| `download_coa_documents.py` | Two-stage: indexes the per-COA landing pages, then downloads 143 public submission and determination PDFs. |
| `download_coa_templates.py` | Fetches FDA's COA qualification templates and guidance -- the required-section checklists. |
| `fda_data/download_ddt.py` | Playwright scraper for the DDT Project Search (Salesforce/Aura). See `DDT_SCRAPER_TODO.md` for the recovery record. |

## Core engine (ported from the rare-disease repo, NOT yet reconfigured)

`reconciliation_orchestrator.py`, `source_reconciliation_agent.py`,
`record_schema.py`, `config.py` -- renamed, but their docstrings still
describe disease resolution. Reconfiguring them is the current work.

## Data (gitignored -- re-downloadable via the scripts above)

Everything lives under `fda_data/`:

| File | Contents |
|---|---|
| `drugsatfda/` | 12 tab-separated tables, 29,198 applications |
| `openfda_indications.csv` | ApplNo -> indication text + rxcui/unii/pharm_class |
| `rxnorm_indications.csv` | rxcui -> MeSH-coded diseases (91,609 rows) |
| `mondo.json` | the full MONDO ontology (~107 MB, kept) |
| `mondo_resolution_index.csv` | 32,095 disease classes, hierarchy, 12 vocabularies of xrefs |
| `coa_compendium.csv` | 199 hand-curated disease/COA/drug rows (June 2021 snapshot) |
| `compendium_drugs_resolved.csv` | those drugs resolved to ApplNo + rxcui |
| `coa_submissions.csv`, `qualified_coas.csv` | 72 + 7 rows |
| `ddt_projects.csv` | 231 DDT project records |
| `coa_documents/` | 143 COA submission + determination PDFs |
| `coa_documents_index.csv` | the map of those documents |
| `coa_templates/` | 6 FDA template/guidance PDFs |

## Setup
An openFDA API key goes in `.env` as `OPENFDA_API_KEY=...` (free, from
https://open.fda.gov/apis/authentication/). Without it you are capped at
1,000 requests/day, which will not complete a full Drugs@FDA run.

`.env` is gitignored. Never commit it.

## Run order

1. `download_openfda_indications.py` (~2.5 hrs, 29,198 calls)
2. `download_rxnorm_indications.py` (reads the openFDA output)
3. `resolve_compendium_drugs.py` (reads the openFDA output)
4. `build_mondo_index.py` (independent, any time)

The COA scripts (`extract_coa_compendium.py`, `download_coa_documents.py`,
`download_coa_templates.py`) are independent and can run any time.
