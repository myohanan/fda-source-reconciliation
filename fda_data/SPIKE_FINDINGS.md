# Spike Findings — FDA Source Reconciliation

Data as of July 12, 2026. Architecture and reasoning live in
`PLANNING.md`.

## 1. Sources on disk (all in fda_data/)

| Source | File | Key | Size |
|---|---|---|---|
| Drugs@FDA | `drugsatfda/` (12 tables) | ApplNo + ApplType | 29,198 applications |
| openFDA indications | `openfda_indications.csv` | ApplNo | 12,572 of 29,198 matched (43%) |
| RxNorm may_treat | `rxnorm_indications.csv` | rxcui -> MeSH | 11,218 of 11,556 rxcuis (97%) |
| COA Compendium | `coa_compendium.csv` | disease name | 199 rows (June 2021 snapshot) |
| Compendium drugs resolved | `compendium_drugs_resolved.csv` | ApplNo + rxcui | 234 OK, 15 flagged |
| COA Submissions | `coa_submissions.csv` | DDT COA # | 72 |
| Qualified COAs | `qualified_coas.csv` | DDT COA # | 7 |
| DDT Project Search | `ddt_projects.csv` | ddtProjectNumber | 231 |
| COA documents | `coa_documents/` | DDT COA # | 143 PDFs |
| COA templates | `coa_templates/` | n/a | 6 PDFs |
| MONDO | `mondo.json` + `mondo_resolution_index.csv` | MONDO ID | 32,095 classes, 10,657 polyhierarchical |
| MeSH | `mesh_desc.xml` + `mesh_disease_index.csv` | MeSH UI | 5,194 descriptors, 59,532 entry terms |
| ICD-10-CM | `icd10cm_index.csv` | code | 74,260 codes |
| SNOMED, MedDRA, CHV, Orphanet, HPO, NCI... | via UMLS API | CUI | ~200 vocabularies |

Every source is reproducible from a committed script. Data is
gitignored; the scripts are the record.

## 2. The COA-number bridge (CONFIRMED)

Three sources share the DDT COA number, spelled differently in each.
`normalize_coa_keys.py` extracts a canonical 6-digit key.

- ddt_projects.csv:      150 distinct COA numbers (of 231 rows; the
  other 81 are non-COA drug-development tools)
- coa_submissions.csv:    71 -- **100% match a DDT project**
- qualified_coas.csv:      7 -- **100% match a DDT project**
- submissions & qualified: 0 overlap -- disjoint BY DESIGN
- in DDT but neither COA file: 72 -- projects the public COA pages do
  not show

## 3. Drugs@FDA IS bridgeable (corrects the original spike)

The first version of this file concluded Drugs@FDA was structurally
unbridgeable. **That is superseded.**

Two independent routes, both confirmed on real data:

    route 1  ApplNo -> openFDA indications_and_usage (prose) -> resolve
    route 2  ApplNo -> rxcui -> RxNorm may_treat -> MeSH -> resolve
    truth    the Compendium's hand-built disease-drug links, resolved
             to the same ApplNo

Agreement is corroboration. Disagreement is a finding.

openFDA coverage is 43% (12,572 / 29,198) -- the misses are older and
discontinued products that predate openFDA labeling. Real coverage
information, not failure; every miss carries a status.

RxNorm's MeSH -> MONDO join closes at 70%. The 30% that does not is
NOT one failure but TWO, and conflating them discards the finding:
- **Carving difference** (not a gap): MED-RT models therapeutic
  TARGETS -- Acidosis, Sleepiness, Abdomen-Acute. MONDO models disease
  IDENTITY. Both are correct; they answer different questions.
- **Xref gap** (a real gap): Acne Vulgaris, Uveal Melanoma. Real
  diseases MONDO knows, whose MeSH cross-reference is unpopulated.

## 4. condition_resolver: 53 of 54 (98%)

Validated by hand against **100% of FDA's COA catalog** -- not sampled,
verified. That is only possible because the catalog is nearly empty,
which is the same fact that makes it a problem.

| Resolved by | Count |
|---|---|
| UMLS Metathesaurus (~200 vocabularies) | 46 |
| ClinicalTrials.gov (trial populations) | 5 |
| Multi-name split (3 names -> 1 CUI) | 1 |
| FDA guidance, cited | 1 |
| **NOT_A_CONDITION (correct)** | **1** |
| CONFLICT_DETECTED | **0** |
| UNRESOLVED | **0** |

**Convergence is countable, not a score:**

    Asthma              36 independent vocabularies  C0004096
    Pain                35                           C0030193
    Multiple Sclerosis  33                           C0026769
    Obesity             33                           C0028754
    Schizophrenia       31                           C0036341

The one NOT_A_CONDITION is `Recovery from surgery and anesthesia`. Its
Context of Use is "patients undergoing ALL FORMS of surgery and
anesthesia" -- not a population. No vocabulary names it. No trial
registers it. **FDA declined the COA at Letter of Intent** -- for
psychometric reasons (a composite score "not sufficiently well-defined
for regulatory use"), which is a separate fact that happens to coincide.
The Disease/Condition field holds a clinical CONTEXT, not a condition.

## 5. FDA's condition field is written in TRIAL-ENROLLMENT language

Five conditions no clinical vocabulary carries -- and every one is in
the trial registry:

    Acute Bacterial Skin and Skin Structure Infection     7 trials
    Non-Cystic Fibrosis Bronchiectasis                   11 trials
    Community-Acquired Bacterial Pneumonia                5 trials
    Hospital-acquired Bacterial Pneumonia                 5 trials
    Dystrophinopathy                                      5 trials

These are not disease names. They are pathogen class + anatomic site +
acuity, or a disease with an exclusion, or an umbrella covering two
dystrophies with one instrument (Dystrophinopathy's Context of Use:
"Duchenne OR Becker"). A COA exists to be used IN A TRIAL, so the field
speaks the registry's language.

**And a keyword approach gets this exactly wrong.** It would map
"Non-Cystic Fibrosis Bronchiectasis" to "bronchiectasis" and SILENTLY
ENROLL the cystic fibrosis patients FDA deliberately excluded. The
exclusion is not noise in the name. It is the trial design.

## 6. The catalog: what is actually in it

**54 conditions. 7 ever qualified. Nothing since 2020.**

Dated activity across all 54 COAs:
- 2011-2016: 29 (53%)
- 2017-2020: 25 (46%) -- including 2019, the busiest year on record
- **2021-2026: 0**

The Compendium was last published **June 2021** -- it compiles work
already done. No qualification has been added since.

**Absent from the catalog:** breast cancer, ovarian, cervical,
endometrial, uterine, prostate, colorectal, pancreatic cancer.
Myocardial infarction. Endometriosis, preeclampsia, postpartum
depression, menopause, osteoporosis.

The entire oncology catalog is five entries: `Cancer`, `NSCLC`, `SCLC`,
`Renal cell carcinoma`, `Plexiform neurofibroma`.

**FDA knows tamoxifen treats breast cancer** -- it is on the approved
label (NDA021807) and coded in RxNorm (MeSH D001943). And there is no
qualified instrument to measure a breast cancer trial's outcomes. The
drug exists. The endpoint does not.

## 7. Why a search box cannot fix this

A developer types "breast cancer" into FDA's page and gets a blank. They
learn NOTHING -- the blank is indistinguishable from a typo, a search
failure, or a disease FDA never considered.

And a keyword system has exactly ONE relation available to it: "same
as." FDA's own data requires at least four:

    NSCLC              is a CHILD of lung cancer
    SCLC               is a SIBLING of NSCLC
    "Cancer"           is a REMOTE ANCESTOR of both
    chronic HF         is a DIFFERENT CONCEPT from congestive HF
                       (C0264716 vs C0018802 -- confirmed at CUI level)

No number of synonyms expresses a subsumption. And a synonym list can
only contain words for things that ARE in the catalog -- so it can never
say "breast cancer exists and we do not have it." **Absence has no
entry to hang a keyword on.**

## 8. Structural: how the four FDA systems are maintained

- **COA Compendium**: hand-curated PDF, by CDER review division (34 of
  them), published June 2021, no update mechanism. FDA's own language:
  it "collates and summarizes" -- collates, not integrates.
- **DDT Project Search**: live Salesforce/Aura app with an API
  underneath. Updates. (Required a scripted capture; GUI clicking
  failed entirely.)
- **COA submissions / qualified**: server-rendered HTML tables.
- **Drugs@FDA**: periodic bulk download + openFDA API.

Four sources, four update mechanisms, one of which is "a person retypes
it every few years." That is the fingerprint of systems never built to
talk to each other -- and it is the concrete answer to "the foundation
is already built."

## 9. COA documents are public and complete

143 documents retrieved, 0 failures. Under FD&C Act 507, FDA must post
submissions and determination letters. They are NOT on the summary
table and NOT reachable via the DDT records' appianDocIds (internal EDM
IDs; they 404 publicly). They live on per-COA landing pages.

    27  FDA Response (Accepted)         5  FDA Response (NOT Accepted)
    26  Letter of Intent                4  Qualification Statement
    26  Transition Letter to 507        3  Full Qualification Package
    13  Update                          3  Qualification Plan
    13  FDA Response                    2  Review
                                        1  SEALD Review

**Read the shape, not the count.** Only 3 Full Qualification Packages
and 2 Reviews exist. That is not a scraper failure -- it is the
program's actual state. Most projects die at Letter of Intent. The
thinness of the corpus IS the finding about the program.
