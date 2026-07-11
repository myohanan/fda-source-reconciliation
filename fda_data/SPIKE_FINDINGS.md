# Spike Findings — FDA Source Reconciliation

## Downloaded (2 of 4 sources)
- COA Compendium: PDF (fda.gov/media/130138/download). Organized by CDER review division. Not structured data.
- Drugs@FDA: 12 structured tables (fda.gov/media/89850/download). Keyed on ApplNo (drug application number). NO disease/condition field — disease lives only in labeling text.

## Confirmed but not downloaded (need scrapers)
- DDT Project Search: live search database, keyed by project number, no direct download / no obvious API.
- COA Qualification Submissions: HTML tables on a web page.

## Key finding: NO shared key across sources
- Drugs@FDA -> ApplNo (no disease field)
- COA Compendium -> PDF by review division / condition-name-as-text
- DDT Search -> project number, searchable only
Three organizing principles, no bridge. Fragmentation is STRUCTURAL, not accidental.
Connecting COA -> condition -> approved drug requires canonical-object reconciliation.

## Scale of the empty-cell problem
- 86 total COAs published (as of Oct 2024) across DDT + COA website.
- ~7,000 rare diseases + all common conditions = catalog is nearly empty.
- FDA's own studies: qualification throughput is slow and has not improved COA inclusion.
- A webpage refresh addresses none of this.
