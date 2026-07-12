# Spike Findings — FDA Source Reconciliation

Status as of July 11, 2026. One item still running (see §7).

## 1. Sources on disk (all in fda_data/)

| Source | File | Key | Rows |
|---|---|---|---|
| Drugs@FDA | `drugsatfda/` (12 tab-sep tables) | ApplNo + ApplType | 29,198 applications |
| openFDA indications | `openfda_indications.csv` | ApplNo | RUN IN PROGRESS |
| COA Compendium | `coa_compendium.csv` (from PDF) | disease name | 199 |
| COA Submissions | `coa_submissions.csv` (from HTML) | DDT COA # | 72 |
| Qualified COAs | `qualified_coas.csv` (from HTML) | DDT COA # | 7 |
| DDT Project Search | `ddt_projects.csv` (Playwright scrape) | ddtProjectNumber | 231 |
| COA documents | `coa_documents/` | DDT COA # | 143 PDFs |
| COA templates | `coa_templates/` | n/a | 6 PDFs |

Scripts that fetch/build each of these are committed at repo root. The
data itself is gitignored (re-downloadable). The scripts are the record.

## 2. The COA-number bridge — CONFIRMED on real data

Three sources share the DDT COA number, but each spells it differently
and it must be normalized first (`normalize_coa_keys.py`):

- `ddt_projects.csv`      ddtProjectNumber      "DDT-COA-000112"
- `coa_submissions.csv`    (embedded in text)    "DDT COA #000112: ..."
- `qualified_coas.csv`     (embedded in text)    "DDT COA #000084: ..."

Canonical form: 6-digit zero-padded string (e.g. "000112").

Confirmed overlap counts:
- ddt_projects.csv:      150 distinct COA numbers (of 231 rows; the
  other 81 are non-COA drug-development tools, e.g. biomarkers)
- coa_submissions.csv:    71 distinct COA numbers
- qualified_coas.csv:      7 distinct COA numbers
- ddt & submissions:      71 overlap — 100% of submissions match
- ddt & qualified:         7 overlap — 100% of qualified match
- submissions & qualified: 0 overlap — disjoint BY DESIGN (in-process
  vs. completed). Not an error.
- in ddt but in neither COA file: 72 — DDT projects the public COA
  web pages do not show. A real gap the reconciliation surfaces.

## 3. Drugs@FDA — CORRECTION to the original spike conclusion

The first version of this file concluded Drugs@FDA was structurally
unbridgeable: no disease field, no shared key, therefore only fuzzy
disease-name matching across vocabularies. **That is now superseded.**

The openFDA drug label API exposes the same drugs keyed on the SAME
application number (`openfda.application_number`, e.g. "NDA021436"),
and returns in the same record:
- `indications_and_usage` — the disease/condition, as its own field
- `rxcui`, `unii`, `pharm_class_epc` — harmonized coded identifiers

So the bridge is: local Drugs@FDA ApplNo + ApplType -> openFDA label
-> indication text + coded anchors. The rxcui/pharm_class codes are
the more reliable join surface; the indication text is prose (openFDA
does not code it to MedDRA/SNOMED) and needs name-level handling.

Verified live on real records: NDA021436 -> ABILIFY -> schizophrenia;
BLA761234 -> OPDUALAG; NDA020702 -> LIPITOR.

Coverage is PARTIAL and that is expected: older/discontinued products
predate openFDA labeling coverage and return NOT_FOUND. A 200-app
sample from the front of the file (oldest ApplNos) matched only 16/200
(~8%). The overall rate will be higher (newer drugs cluster later in
the file) but a large NOT_FOUND fraction is real coverage information,
not a failure. `download_openfda_indications.py` writes NOT_FOUND /
ERROR / HTTP_nnn as distinct statuses so the gap is visible, never
silent.

The name-matching layer is ALREADY BUILT: `fda_match_util.term_matches`
in the rare-disease repo (whole-word boundary for terms <= 4 chars,
substring for longer; shared by fda_agent and fda_approval_agent so
they cannot drift). It is the right matcher for the COA abbreviations
(CHF, CKD, AOM, CD) embedded in the FDA condition strings.

## 4. The COA Compendium is a VALIDATION SET, not just a source

`extract_coa_compendium.py` pulls 199 rows from the PDF (pdfplumber
table extraction, source page recorded per row for traceback). Each row
carries: division, disease, context_of_use, concept, coa_tool_type,
drug_approval.

The significance: the Compendium is the ONE FDA source that already
links, BY HAND, disease -> COA -> drug -> approval date. 198 of 199
rows name a drug. That is a partial ground-truth set the reconciliation
engine's joins can be checked against.

Two caveats, both real:
- It is dated JUNE 2021. A snapshot, not current state. It has no
  update mechanism — a person retyped it, once. Approvals since then
  are absent. Do not treat it as live truth.
- Multi-drug cells ("1. Brilinta ... 2. Effient ...") and approval
  dates are left as RAW TEXT on purpose. Splitting them is a downstream
  decision; splitting at extraction risks silently mis-associating a
  drug with the wrong disease.

The delta between the 2021 Compendium and the live sources is itself a
measure of how far the hand-built layer has drifted from reality.

## 5. How the four FDA systems are actually maintained

Confirmed from the data, not inferred:
- COA Compendium: hand-curated PDF, organized by CDER review division
  (34 of them), published June 2021, no update mechanism. FDA's own
  language: it "collates and summarizes" — collates, not integrates.
- DDT Project Search: live Salesforce/Aura app with an API underneath
  (required a scripted capture; GUI clicking failed). Updates.
- COA submissions / qualified: server-rendered HTML tables. Update on
  their own cadence.
- Drugs@FDA: periodic bulk download + openFDA API.

Four sources, four different update mechanisms, one of which is "a
person retypes it every few years." That is the fingerprint of systems
never built to talk to each other — and it is the concrete answer to
"the foundation is already built."

## 6. COA submission documents — public, and they exist

Under FD&C Act section 507 (21st Century Cures), FDA must publicly post
COA qualification submissions and its determination letters.

They are NOT on the submissions summary table, and they are NOT
reachable via the DDT records' `appianDocIds` (internal EDM IDs; they
404 publicly). They live on a per-COA landing page — one page per DDT
COA number — each linking ordinary `fda.gov/media/NNNNN/download` PDFs.
`download_coa_documents.py` crawls 63 landing pages and pulls them.

143 documents retrieved, 0 failures. Composition:
-  27  FDA Response (Accepted)
-  26  Transition Letter to 507 Process
-  26  Letter of Intent
-  13  Update
-  13  FDA Response
-   5  FDA Response (NOT Accepted)
-   4  Qualification Statement
-   3  Full Qualification Package
-   3  Qualification Plan
-   2  Review
-   2  FDA Response (Qualified)
-   1  SEALD Review
- plus appendices

**Read the shape, not just the count.** The corpus is dominated by
correspondence. Only 3 Full Qualification Packages and 2 Reviews exist.
That is not a scraper failure — it is the program's actual state: most
projects die at Letter of Intent. Published finding: 86 COAs listed, 7
ever qualified (8.1%), 1 denied, none qualified since 2020, none
post-Cures qualified at all, and 46.7% of submissions exceeded the
published review timelines. The thinness of the corpus IS the finding
about the program.

## 7. openFDA coverage — RUN COMPLETE

`download_openfda_indications.py` finished. All 29,198 applications.

- **OK (indication retrieved):     12,572  (43%)**
- NOT_FOUND (no openFDA label):    16,624  (57%)
- HTTP_502 / HTTP_500:                  2  (network, re-runnable)

12,183 rows carry an rxcui — these feed the RxNorm coded route
(`download_rxnorm_indications.py`).

The 57% NOT_FOUND is REAL COVERAGE INFORMATION, not a failure. Older
and discontinued products predate openFDA labeling coverage. A sample
from the front of the file (the oldest ApplNos) matched only ~8%; the
overall 43% reflects newer drugs clustering later. Every miss is
recorded with a status, so the gap is visible rather than silent.

Only 2 network errors across 29,198 calls.

**This settles the correction in §3: Drugs@FDA is bridgeable.** 12,572
applications now carry an indication plus coded anchors, keyed on
ApplNo — the source the original spike called structurally
unbridgeable.

## 7b. Compendium drug resolution — RUN COMPLETE

`resolve_compendium_drugs.py` finished. The validation set now connects
to the pipeline it validates.

Parsed from the 199 Compendium rows:
- 279 drug entries, 237 distinct brands
- 7 non-drug cells (Qualified COA references) — correctly refused, not
  forced into a false match

Resolved against openFDA:
- **OK (brand resolved, generic corroborated):  234**
- GENERIC_MISMATCH (flagged, NOT accepted):      15
- NOT_A_DRUG:                                     7
- 209/237 brands resolved (28 unknown to openFDA — older/withdrawn)

The GENERIC_MISMATCH rows are the point: a brand-name collision that
silently resolved to the wrong application would corrupt the validation
set, which is worse than a gap in it. They are surfaced, not accepted.

FDA's hand-built disease-drug links now carry ApplNo and rxcui, so they
can be compared directly against both pipeline routes:

    route 1: ApplNo -> openFDA indication text -> MONDO
    route 2: ApplNo -> rxcui -> RxNorm may_treat -> MeSH -> MONDO
    truth:   the Compendium's hand-built disease for that same ApplNo

Three independent angles on one claim. Agreement is corroboration;
disagreement is a finding.

## 7c. RxNorm coded route — RUN COMPLETE

`download_rxnorm_indications.py` finished. 11,556 distinct rxcuis.

- **rxcuis with >= 1 coded indication: 11,218 / 11,556  (97%)**
- rows written: 91,609 (a drug averages ~8 may_treat concepts)

CAVEAT ON SCOPE: MED-RT `may_treat` is BROADER than an FDA-approved
indication. It captures therapeutic use, including off-label and
class-level use, and returns some non-indication artifacts (e.g.
"Drug Hypersensitivity" for aripiprazole, which is a contraindication).
~8 concepts per drug is NOT 8 approved uses. This is a CORROBORATING
route, not a replacement for the label.

## 7d. The MeSH -> MONDO join: 70%, and the 30% is INFORMATION

Route 2 depends on RxNorm's MeSH IDs reaching a MONDO class. Tested on
real data:

- distinct MeSH disease IDs from RxNorm:  1,383
- distinct MeSH IDs in MONDO xrefs:       8,089
- **MeSH IDs that reach MONDO:  978 / 1,383  (70%)**

The 405 that do NOT reach MONDO are not one failure. They are TWO, and
conflating them would discard the finding:

**(a) NOT A DISEASE ENTITY — a carving difference, not a gap.**
MED-RT is organized for therapeutic reasoning ("what does this drug
treat"); MONDO models disease IDENTITY. A concept can be a legitimate
therapeutic target without being a disease entity. Observed:
  D000006   Abdomen, Acute            (a presentation)
  D000077260 Sleepiness               (a symptom)
  D000087122 Mania                    (a state)
  D000137   Acid-Base Imbalance       (a physiological derangement)
  D000138   Acidosis
  D000267   Tissue Adhesions          (a pathological finding)
  D000013   Congenital Abnormalities  (a category header)
  D000081207 Primary Immunodeficiency Diseases  (a category header)
These are BOTH CORRECT. The two ontologies are answering different
questions. This is not a miss to be patched.

**(b) XREF GAP — a real disease MONDO knows, whose MeSH cross-reference
is simply not populated.** Observed:
  D000152    Acne Vulgaris
  D000080223 Chronic Urticaria
  D000098943 Uveal Melanoma
  D000086002 Mesothelioma, Malignant
  D000077216 Carcinoma, Ovarian Epithelial
  D000070779 Giant Cell Tumor of Tendon Sheath
These almost certainly EXIST in MONDO under their own labels; only the
xref is missing.

**ARCHITECTURAL CONSEQUENCE.** A resolver that treats "MeSH ID absent
from MONDO" as a single failure state throws information away. The
honest states are at least three:

  RESOLVED             reaches a MONDO class
  NOT_A_DISEASE_ENTITY MED-RT's target is not a disease in MONDO's
                       model. A carving difference. NOT a gap.
  XREF_GAP             a real disease MONDO knows but has not
                       cross-referenced to MeSH. A genuine gap.

**OPEN, NOT YET BUILT:** the XREF_GAP class is recoverable by resolving
the MeSH LABEL against MONDO's labels and synonyms, instead of against
the xref. That is a second angle on the same object -- resolution, not
an exception rule -- and it should lift the effective rate well above
70% without a single hand-coded case. Decide whether to build it.

This is the multi-authority carving problem, measured: the vocabularies
do not merely disagree, they cut the world differently, and the
difference is substantive. Any single authority silently imposes its own
angle and the pipeline cannot see that it has done so.

## 8. Scale context (the "empty cell" problem, quantified)

86 total COAs published (COA website + DDT combined) as of Oct 2024,
against thousands of conditions. FDA's own research: the DDT
qualification program has not significantly improved COA inclusion in
clinical development, due to slow and unpredictable review timelines.
The bottleneck is throughput — expert reviewer time — not policy. A
webpage refresh addresses none of this.
