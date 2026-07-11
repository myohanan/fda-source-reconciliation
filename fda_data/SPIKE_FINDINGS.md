# Spike Findings — FDA Source Reconciliation

## Sources on disk (fda_data/)
- Drugs@FDA: 12 relational .txt tables. Keyed on ApplNo (drug
  application number). NO disease/condition field — disease lives only
  in labeling text (ApplicationDocs).
- COA Compendium: PDF (fda.gov/media/130138/download). Organized by
  CDER review division. Not structured data.
- COA Qualification Submissions: coa_submissions.csv (parsed from HTML).
  Has Disease/Condition column + DDT COA number embedded in text.
- Qualified COAs: qualified_coas.csv (parsed from HTML). Same structure.
- DDT Project Search: ddt_projects.csv (231 rows, Playwright scrape).
  Keyed on ddtProjectNumber. See DDT_SCRAPER_TODO.md for re-scrape steps.

## The shared key: DDT COA number (CONFIRMED on real data)
The DDT COA number bridges three of the four sources, but each source
spells it differently and it must be normalized first:
- ddt_projects.csv       ddtProjectNumber      "DDT-COA-000112"
- coa_submissions.csv     (embedded in text)    "DDT COA #000112: ..."
- qualified_coas.csv      (embedded in text)    "DDT COA #000084: ..."
Canonical form: 6-digit zero-padded string (e.g. "000112").
Extraction/join logic: normalize_coa_keys.py (repo root).

## Overlap counts (from normalize_coa_keys.py, confirmed this session)
- ddt_projects.csv:      150 distinct COA numbers
- coa_submissions.csv:    71 distinct COA numbers
- qualified_coas.csv:      7 distinct COA numbers
- ddt & submissions overlap:   71  (100% of submissions match a DDT project)
- ddt & qualified overlap:      7  (100% of qualified match a DDT project)
- submissions & qualified overlap: 0 (disjoint by design: in-process vs done)
- in ddt but in neither COA file: 72 (DDT projects not shown on the COA
  web pages — a real gap the reconciliation surfaces)

## Note on counts
The DDT scrape holds 231 records total; only 150 carry a DDT COA number.
The other 81 are non-COA drug-development tools (e.g. biomarkers), which
is expected — DDT covers more than COAs.

## Key structural finding
Three sources share the DDT COA number (clean join after normalization).
Drugs@FDA shares NO key with any of them — it has no COA number and no
disease field. Bridging Drugs@FDA requires disease-NAME matching across
vocabularies (the canonical-object problem), not a key join. That is the
one genuinely harder join and the next design question.

## Scale context
86 total COAs published (COA website + DDT combined) as of Oct 2024,
against thousands of conditions — the "empty-cell" problem, quantified.
FDA own research: the DDT qualification program has not significantly
improved COA inclusion in clinical development, due to slow/unpredictable
review timelines. A webpage refresh addresses none of this.
