# PLANNING.md — FDA Source Reconciliation

## 0. What this is
A spinoff of the rare-disease endpoint library's canonical-object
reconciliation engine, applied to FDA's own fragmented COA/DDT/Drugs@FDA
data. Triggered by an FDA comms response (Nichols, 7/9/26) that read the
rare-disease proposal as a front-end problem ("refresh the webpage") when
it is structurally a backend/reconciliation problem — the same category
error the user made pre-canonical-object-breakthrough on gene resolution.

## 1. The four sources — status as of this repo
| Source | Format | Key | Status |
|---|---|---|---|
| Drugs@FDA | 12 relational .txt tables | ApplNo (drug application #) — no disease field | Downloaded, in `fda_data/drugsatfda/` |
| COA Compendium | PDF | Organized by CDER review division; not structured | Downloaded, `fda_data/coa_compendium.pdf` |
| COA Qualification Submissions | HTML tables (parsed to CSV) | Disease/Condition column + DDT COA # | Extracted, `fda_data/coa_submissions.csv` (72 rows) |
| Qualified COAs | HTML tables (parsed to CSV) | Disease/Condition column + DDT COA # | Extracted, `fda_data/qualified_coas.csv` (7 rows) |
| DDT Project Search | Live search DB, no API found | ddtProjectNumber | Scraped via Playwright, `fda_data/ddt_projects.csv` (231 rows) |

## 2. Central finding (confirmed on real data, not inferred)
No single key bridges all four sources.
- `ddtProjectNumber` / `DDT COA #` bridges DDT Project Search ↔ COA
  Submissions/Qualified COAs cleanly (HIGH_CONFIDENCE join).
- Drugs@FDA has no disease/condition field and no COA number — bridging
  it to the others requires matching on disease/condition NAME across
  vocabularies (the canonical-object problem), not a key join.
- Fragmentation is STRUCTURAL (three organizing principles: application
  number, project number, free-text condition name), not accidental.

## 3. Why this is not "harder" than rare disease (settled — do not relitigate)
Initial concern that name-matching across FDA sources would be harder than
disease resolution was raised and withdrawn after checking real data:
- COA Submissions conditions are common diseases (~51 unique), not rare —
  mature ontology coverage (MONDO/ICD/SNOMED) already exists.
- Abbreviations are pre-embedded in the source strings themselves
  (e.g. "Chronic Heart Failure (CHF)") — FDA hands you the mapping.
- The Krabbe/UBTF/FOXG1-Rett-collision problems solved for rare disease
  were harder than anything expected here.
- Residual risk: Drugs@FDA's disease/condition is buried in labeling text
  (ApplicationDocs), not a structured field — an extraction task, not a
  reconciliation-difficulty problem.

## 4. Architecture mapping (canonical-object engine → FDA domain)
| Gene resolution architecture | FDA reconciliation |
|---|---|
| Disease Name (ambiguous label) | COA / condition / drug (ambiguous across sources) |
| Reconcile Orphanet/OMIM/MONDO/HGNC | Reconcile Drugs@FDA / COA Compendium / COA Submissions / DDT |
| disease_class → lookup_strategy | source-type → reconciliation-strategy (clean-key join vs. name-match) |
| Canonical Disease Object | Canonical COA/condition/drug record |
| CONFLICT_DETECTED | Sources name the same thing differently |
| source_of_truth governance | Which FDA source is authoritative per field |

Reuses, unchanged in principle: canonical-object reconciliation,
CONFLICT_DETECTED / HUMAN_REVIEW_REQUIRED states, source-of-truth
governance. Ported (not yet reconfigured) into this repo's root .py files
per commit 9b3e246.

## 5. Demonstration plan — three or four anchor cases
Same coverage-set logic as the Cat 1-4 rare-disease demo diseases,
transplanted. Proposed anchors (NOT yet built or chosen against real
records):
- Condition-anchored: "for this disease, what COAs/drugs/trials exist"
- COA-anchored: "for this COA, what conditions/drugs use it, what's its
  qualification status"
- Drug-anchored: "for this approved drug, what COAs measured its endpoints"
- At least one case should surface a genuine CONFLICT_DETECTED /
  no-clean-match result (e.g., a Drugs@FDA record with no name match to
  COA data) — the demo should show the conflict state working, not hide it.

Specific diseases/COAs/drugs for these four cases: NOT YET SELECTED.

## 6. Scale context
FDA's own cited figure: 86 total COAs published (COA website + DDT
combined) as of Oct 2024, against thousands of conditions — the
"empty-cell" problem this project targets, quantified. FDA's own research
also states the DDT qualification program has not significantly improved
COA inclusion in clinical development, due to slow/unpredictable review
timelines.

## 7. Open items / not yet done
- Reshape `reconciliation_orchestrator.py`, `source_reconciliation_agent.py`,
  `record_schema.py`, `config.py` for the FDA sources specifically — these
  are still the ported rare-disease versions (renamed, not reconfigured).
- Parse disease/condition out of Drugs@FDA's ApplicationDocs labeling text.
- Select and build the 3-4 demonstration cases (§5).
- `DDT_SCRAPER_TODO.md` — check against current state; scraper appears
  complete (231/231 records) per commit 900ad7b, confirm TODO is stale.
- No serving layer, no front end — out of scope for this repo unless
  scoped in later.

## 8. Explicitly NOT part of this repo
The FDA Reviewer Tool (CONSORT-based trial-report auditing) is a separate
project with its own PLANNING.md elsewhere. Do not conflate the two —
they share the canonical-object engine as a common ancestor but are
different tools with different question libraries and different data.
