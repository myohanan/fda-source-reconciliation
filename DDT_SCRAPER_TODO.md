# DDT Project Search scraper — next session task

## Status: endpoint works, but needs the FILTER-search call captured live.

Site: https://force-dsc.my.site.com/ddt/s/  (Salesforce Aura / Experience site)
Aura endpoint: /ddt/s/sfsites/aura?r=1  (POST, HTTP 200 confirmed)

## Aura context (captured, may expire — re-grab if calls fail):
fwuid: OUcwT3JDYUZld21JQ2ZOckR1VnppUWtVMjdnTGFERUU2S3FfSVdrcU92bkExNC4xOTIuODM4ODYwOA
app: siteforce:communityApp
loaded APPLICATION@markup://siteforce:communityApp : 1684_KM73-ooay8cQA67rJ6OvFA

## KEY FINDING from this session:
- The GLOBAL SEARCH BAR calls ScopedResultsDataProvider/getItems with
  scope "ContentDocument" -> returns PDFs/documents, NOT project records. Wrong call.
- The PROJECT RECORDS come from the SEARCH OPTIONS FILTER PANEL
  (Program / Stage / Disease / Therapeutic Area), not the global search bar.
- Blind ApexActionController guessing failed (needs valid CSRF token + real
  controller name). Must capture the real call live.

## NEXT SESSION - exact capture (do the FILTER search, not the search bar):
1. https://force-dsc.my.site.com/ddt/s/  -> DevTools -> Network -> filter "aura"
2. In "Search Options": pick a Program (e.g. COAQP), click > to move it to Selected,
   then click that panel's Search button.
3. Find the NEW aura call whose Preview tab shows PROJECT rows
   (disease, COA/project number, stage) -- NOT PDF file results.
4. Right-click that request -> Copy -> Copy as cURL. Paste the whole thing to Claude.
   (Copy as cURL captures the token + exact payload -> Claude builds the scraper.)

## Then: download_ddt.py POSTs that action, paginates, writes fda_data/ddt_projects.csv
## Note: DDT data overlaps coa_submissions.csv (already have). NOT blocking.
