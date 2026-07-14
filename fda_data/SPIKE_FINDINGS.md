# Spike Findings — FDA Source Reconciliation

Data as of July 12, 2026. Architecture lives in `PLANNING.md`. The
parked axis-schema experiment lives in `COA_AXES.md`.

Everything here was MEASURED on FDA's own public data. Nothing is
inferred.

---

## 1. What is actually in FDA's COA catalog

**54 conditions. 7 ever qualified. Nothing since 2020.**

Dated activity across all 54 COAs:

| Period | COAs | Note |
|---|---|---|
| 2011–2016 | 29 (53%) | |
| 2017–2020 | 25 (46%) | including 2019, the busiest year on record |
| **2021–2026** | **0** | |

The COA Compendium — FDA's only source linking a disease to an endpoint
to the drug approved using it — was last published **June 2021**. It
compiles work already done. It has no update mechanism: a person retyped
it, once.

**Absent from the catalog entirely:** breast cancer, ovarian, cervical,
endometrial, uterine, prostate, colorectal, pancreatic. Myocardial
infarction. Endometriosis, preeclampsia, postpartum depression,
menopause, osteoporosis.

The entire oncology catalog is **five entries**: `Cancer`, `NSCLC`,
`SCLC`, `Renal cell carcinoma`, `Plexiform neurofibroma`.

---

## 2. FDA has the drug and not the endpoint

**FDA knows tamoxifen treats breast cancer.** It is on the approved
label (NDA021807) and coded in RxNorm (MeSH D001943). Both of FDA's own
systems say so, unambiguously.

**And FDA has no qualified instrument to measure a breast cancer trial's
outcomes.**

Measured: **738 approved drug applications** for breast cancer, 180
corroborated by both independent routes. **Zero COAs.**

The drug exists. The endpoint does not.

---

## 3. THE FINDING: FDA cannot see which of its COAs matter

FDA's four sources track **qualification**. Nothing tracks **use**.

Measured against the trial registry, where sponsors must declare their
endpoints before a trial runs:

| Instrument | Trials | As PRIMARY | As secondary | Qualified? |
|---|---|---|---|---|
| **Short Physical Performance Battery** | **1,710** | **356** | 631 | **NO** |
| **Kansas City Cardiomyopathy Questionnaire** | **1,029** | **117** | 499 | **YES** |
| **Symbol Digit Modalities Test** | **652** | **104** | 261 | **NO** |
| EXACT (COPD) | 38 | 3 | 16 | YES |
| NSCLC-SAQ | 33 | 0 | 17 | YES |
| SMDDS (depression) | 9 | 0 | 8 | YES |
| E-RS:COPD | 5 | 0 | 3 | YES |
| **Asthma Daytime Symptom Diary** | **8** | **0** | 7 | **YES** |
| **IBS-C Diary** | **0** | **0** | 0 | **YES** |

**The KCCQ is a primary endpoint in 117 trials** — tirzepatide,
mavacamten, aficamten. It is infrastructure.

**Two qualified COAs have never been a primary endpoint in any trial.**
One appears in no trial at all.

**And the two most-used instruments in the catalog were never
qualified.** The Short Physical Performance Battery — 1,710 trials, 356
primary endpoints — sits in the submissions pile.

**50 of 80 catalog instruments appear in ZERO trials.**

Nothing in any FDA source distinguishes any of these from any other.
They are all on the same list, described the same way.

*(Caveat, stated: the search is text-based and over-returns. The counts
are directional, not exact. The SHAPE is unmistakable.)*

---

## 4. A qualified COA was NOT used in the approval it should have carried

**Tezspire (tezepelumab)** — approved for asthma, December 2021.

FDA has a **qualified asthma COA**: DDT COA #000006, the Asthma Daytime
Symptom Diary (ADSD) — **six items, scored 0 to 10**, developed by
C-Path's PRO Consortium.

**NAVIGATOR**, tezepelumab's pivotal Phase 3, registered as a key
secondary endpoint: *"Change from baseline in Asthma Symptom Diary."*

**It is a DIFFERENT instrument.** The ASD used in NAVIGATOR is **ten
items, scored 0 to 4**, from Globe et al 2015. Different developer,
different item count, different scale.

Confirmed by the registry itself: searching outcome text for "Asthma
Symptom Diary" returns 22 trials; "Asthma Daytime Symptom Diary" returns
8. **Different searches, different trials.** If they were one instrument
the searches would collide.

So: FDA qualified an asthma diary. A sponsor ran the pivotal trial with
a *different, unqualified* diary. **FDA approved the drug.** And no FDA
source records any of it.

*(A string matcher called this a hit. It looked like a hit. It read like
a hit. Verification against the psychometric papers caught it. That is
why `endpoint_search` returns VERBATIM text and never a boolean.)*

---

## 5. condition_resolver: 53 of 54 (98%)

Validated by hand against **100% of FDA's COA catalog** — not sampled,
verified. That is only possible because the catalog is nearly empty,
which is the same fact that makes it a problem.

| Resolved by | Count |
|---|---|
| UMLS Metathesaurus (~200 vocabularies) | 46 |
| ClinicalTrials.gov (trial populations) | 5 |
| Multi-name split (3 names → 1 CUI) | 1 |
| FDA guidance, cited | 1 |
| **NOT_A_CONDITION (correct)** | **1** |
| CONFLICT_DETECTED | **0** |
| UNRESOLVED | **0** |

**Convergence is countable, not a score:**

    Asthma              36 independent vocabularies  C0004096
    Pain                35                           C0030193
    Multiple Sclerosis  33                           C0026769
    Obesity             33                           C0028754

The one NOT_A_CONDITION is `Recovery from surgery and anesthesia`. Its
Context of Use is "patients undergoing ALL FORMS of surgery and
anesthesia" — not a population. No vocabulary names it. No trial
registers it. **FDA declined the COA at Letter of Intent** — for
psychometric reasons (a composite score "not sufficiently well-defined
for regulatory use"). The Disease/Condition field holds a clinical
CONTEXT, not a condition.

---

## 6. FDA's condition field is written in TRIAL-ENROLLMENT language

Five conditions no clinical vocabulary carries — and every one is in the
trial registry:

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
"Non-Cystic Fibrosis Bronchiectasis" to "bronchiectasis" and **silently
enroll the cystic fibrosis patients FDA deliberately excluded.** The
exclusion is not noise in the name. It is the trial design.

---

## 7. Hierarchy coverage — measured across all 54

| Source | Conditions with a parent |
|---|---|
| SNOMED | 47/54 (87%) |
| MeSH | 43/54 (79%) |
| NCIt | 43/54 (79%) |
| MONDO | 38/54 (70%) |
| ICD-10-CM | 36/54 (66%) |
| MedDRA | 31/54 (57%) |

19 conditions have a parent in **all six**; 18 more in five.

**7 conditions have NO parent in ANY source** — and they are exactly the
five trial populations, the guidance-defined construct, and the
non-condition. **That is a CATEGORY FACT, not a coverage gap.** A trial
enrollment definition has no taxonomic parent because it is not the kind
of thing that has one.

---

## 8. Why the four sources cannot be connected as they stand

| Source | How it is maintained |
|---|---|
| COA Compendium | Hand-curated PDF, by CDER review division (34 of them), published June 2021, no update mechanism. FDA's own language: it "collates and summarizes" — collates, not integrates. |
| DDT Project Search | Live Salesforce/Aura app. Required a scripted capture; GUI clicking failed entirely. |
| COA submissions / qualified | Server-rendered HTML tables. |
| Drugs@FDA | Periodic bulk download + openFDA API. No disease field at all. |

Four sources, four update mechanisms, one of which is "a person retypes
it every few years." **That is the fingerprint of systems never built to
talk to each other** — and it is the concrete answer to "the foundation
is already built."

---

## 9. Drugs@FDA IS bridgeable (corrects the original spike)

The first version of this file concluded Drugs@FDA was structurally
unbridgeable. **Superseded.**

Two independent routes, both confirmed on real data:

    route 1  ApplNo -> openFDA indications_and_usage (PROSE)
    route 2  ApplNo -> rxcui -> RxNorm may_treat -> MeSH -> the CUI (CODED)

Breast cancer: **738 applications**, 180 found by BOTH routes, 515 coded
only, 43 label only.

**Agreement is corroboration. Disagreement is a finding.** And the
disagreement is informative:

  - **Label-only** includes **Cardiolite** — a *cardiac imaging agent*
    whose label mentions breast tissue attenuation. **A false positive
    from the string match** — visible only because the tool prints the
    indication text instead of a count.
  - **Coded-only** includes chlorambucil and cyclophosphamide. MED-RT
    says therapeutic use; the approved label does not name breast
    cancer. `may_treat` is BROADER than an approved indication.

*(The coded route initially returned ZERO drugs for breast cancer. The
cause: MONDO's `xref_mesh` is **EMPTY** for MONDO:0007254, while RxNorm
links 826 rxcuis to MeSH D001943. The data was on disk. The BRIDGE was
missing — for the most common cancer in American women. Fixed by asking
UMLS directly: it IS the metathesaurus.)*

---

## 10. COA documents are public and complete

143 documents retrieved, 0 failures. Under FD&C Act 507, FDA must post
submissions and determination letters. They are NOT on the summary table
and NOT reachable via the DDT records' appianDocIds. They live on
per-COA landing pages.

    27  FDA Response (Accepted)         5  FDA Response (NOT Accepted)
    26  Letter of Intent                4  Qualification Statement
    26  Transition Letter to 507        3  Full Qualification Package
    13  Update                          3  Qualification Plan
    13  FDA Response                    2  Review
                                        1  SEALD Review

**Read the shape, not the count.** Only **3 Full Qualification Packages**
exist. That is not a scraper failure — it is the program's actual state.
Most projects die at Letter of Intent.

**And 4 of the 7 qualified COAs have NO Full Qualification Package
posted at all** — including the **KCCQ**, the most-used COA in the
catalog. Its qualification evidence is not public. The posting is
inconsistent: some COAs expose FDA's internal reviews, some expose the
requestor's package, and the most consequential one exposes neither.

---

## 11. Sources on disk (all in fda_data/)

| Source | File | Size |
|---|---|---|
| Drugs@FDA | `drugsatfda/` (12 tables) | 29,198 applications |
| openFDA indications | `openfda_indications.csv` | 12,572 of 29,198 (43%) |
| RxNorm may_treat | `rxnorm_indications.csv` | 11,218 of 11,556 rxcuis (97%) |
| COA Compendium | `coa_compendium.csv` | 199 rows (June 2021) |
| Compendium drugs resolved | `compendium_drugs_resolved.csv` | 234 OK, 15 flagged |
| COA submissions / qualified | `coa_submissions.csv`, `qualified_coas.csv` | 72 + 7 |
| DDT projects | `ddt_projects.csv` | 231 |
| COA documents | `coa_documents/` | 143 PDFs |
| COA templates | `coa_templates/` | 6 PDFs |
| COA resolution | `coa_resolution.csv` | 54, re-resolved |
| COA usage | `coa_usage.csv` | 80 instruments |
| Hierarchy coverage | `hierarchy_coverage.csv` | 54 x 6 sources |
| MONDO | `mondo.json` + index | 32,095 classes |
| MeSH | `mesh_desc.xml` + index | 5,194 descriptors |
| ICD-10-CM | `icd10cm_index.csv` | 74,260 codes |
| CDISC instruments | `cdisc_instruments.csv` | 252, item-level |
| SNOMED, MedDRA, CHV, Orphanet, NCIt... | via UMLS API | ~200 vocabularies |

Every source is reproducible from a committed script. Data is
gitignored; **the scripts are the record.**

---

## 12. The COA-number bridge (CONFIRMED)

Three sources share the DDT COA number, spelled differently in each.
`normalize_coa_keys.py` extracts a canonical 6-digit key.

- ddt_projects.csv: 150 distinct COA numbers (of 231 rows; the other 81
  are non-COA drug development tools — biomarkers, animal models)
- coa_submissions.csv: 71 — **100% match a DDT project**
- qualified_coas.csv: 7 — **100% match a DDT project**
- submissions & qualified: 0 overlap — **disjoint BY DESIGN**
- in DDT but neither COA file: **72** — projects the public COA pages do
  not show
