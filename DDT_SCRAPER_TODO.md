# DDT Project Search scraper — how it works

## STATUS: COMPLETE. The scrape succeeded.

`fda_data/download_ddt.py` captured all 231 DDT project records into
`fda_data/ddt_projects.csv`. This file is kept as the RECOVERY RECORD:
the Salesforce/Aura context below expires, and if the scraper stops
working this is how to re-capture it.

## The site

https://force-dsc.my.site.com/ddt/s/ — a Salesforce Aura / Experience
site. Aura endpoint: `/ddt/s/sfsites/aura?r=1` (POST).

## Aura context (CAPTURED — WILL EXPIRE; re-grab if calls fail)
## The key finding (why the obvious approach fails)

- The GLOBAL SEARCH BAR calls `ScopedResultsDataProvider/getItems` with
  scope "ContentDocument" — it returns PDFs/documents, NOT project
  records. **Wrong call.**
- The PROJECT RECORDS come from the SEARCH OPTIONS FILTER PANEL
  (Program / Stage / Disease / Therapeutic Area), not the search bar.
- Blind ApexActionController guessing fails (needs a valid CSRF token
  and the real controller name). The call must be captured live.
- GUI clicking failed entirely. The scripted approach worked on the
  first real attempt.

## To re-capture if the scraper breaks

1. Open https://force-dsc.my.site.com/ddt/s/ -> DevTools -> Network ->
   filter "aura"
2. In "Search Options": pick a Program (e.g. COAQP), click `>` to move
   it to Selected, then click that panel's Search button.
3. Find the NEW aura call whose Preview tab shows PROJECT rows
   (disease, COA/project number, stage) — NOT PDF file results.
4. Right-click that request -> Copy -> Copy as cURL. That captures the
   token and exact payload; rebuild the scraper from it.

## Notes on the data

- 231 records total; only 150 carry a DDT COA number. The other 81 are
  non-COA drug-development tools (e.g. biomarkers). Expected.
- `salesforceDocIds` is all zeros — dead field.
- `appianDocIds` holds real internal EDM IDs (e.g. 224647), but they do
  NOT resolve publicly (fda.gov/media/<id>/download 404s). The public
  COA documents are reached instead through the per-COA landing pages —
  see `download_coa_documents.py`.
- `projectURL` is a raw un-evaluated Excel formula string
  (`=HYPERLINK("...","DDT-COA-000084")`), an artifact of the capture.
  Regex it if you need the value.
