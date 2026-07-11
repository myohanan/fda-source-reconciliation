# FDA Source Reconciliation

Reconciles FDA's fragmented COA / DDT / Drugs@FDA data into canonical
records. A spinoff of the rare-disease endpoint library's
canonical-object engine, pointed at FDA's own sources.

**Start here:** `PLANNING.md` (architecture, scope, next steps) and
`fda_data/SPIKE_FINDINGS.md` (what the data actually shows).

## The problem, in one line

The four FDA resources do not share a common key, so a website refresh
cannot display connections that do not exist underneath.

## What is where

### Scripts (committed; these are the record)

| Script | What it does |
|---|---|
| `normalize_coa_keys.py` | The COA-number bridge. Normalizes DDT-COA-000112 / DDT COA #000112 to a canonical 6-digit key and reports overlap across the three COA sources. **This is the proven join.** |
| `download_openfda_indications.py` | Bridges Drugs@FDA (no disease field) to indication text + rxcui/unii codes via the openFDA label API, keyed on ApplNo. Needs `OPENFDA_API_KEY` in `.env`. |
| `extract_coa_compendium.py` | Extracts the COA Compendium PDF into `coa_compendium.csv` (199 rows) via pdfplumber. |
| `download_coa_documents.py` | Two-stage: indexes the per-COA landing pages, then downloads the 143 public submission and determination PDFs. |
| `download_coa_templates.py` | Fetches FDA's COA qualification templates and governing guidance — the required-section checklists. |
| `fda_data/download_ddt.py` | Playwright scraper for the DDT Project Search (Salesforce/Aura). See `DDT_SCRAPER_TODO.md`. |

### Core engine (ported from the rare-disease repo, NOT yet reconfigured)

`reconciliation_orchestrator.py`, `source_reconciliation_agent.py`,
`record_schema.py`, `config.py` — renamed but their docstrings still
describe disease resolution. Reconfiguring them is the next work.

### Data (gitignored — re-downloadable via the scripts above)

Everything lives under `fda_data/`:

- `drugsatfda/` — 12 tab-separated tables, 29,198 applications
- `openfda_indications.csv` — ApplNo -> indication + coded anchors
- `coa_compendium.csv` — 199 hand-curated disease/COA/drug rows
- `coa_submissions.csv`, `qualified_coas.csv` — 72 + 7 rows
- `ddt_projects.csv` — 231 DDT project records
- `coa_documents/` — 143 COA submission + determination PDFs
- `coa_documents_index.csv` — the map of those documents
- `coa_templates/` — 6 FDA template/guidance PDFs

## Setup
An openFDA API key goes in `.env` as `OPENFDA_API_KEY=...` (free, from
https://open.fda.gov/apis/authentication/). Without it you are capped at
1,000 requests/day, which will not complete a full Drugs@FDA run.

`.env` is gitignored. Never commit it.
