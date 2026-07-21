# Spike Findings — FDA Source Reconciliation

Data as of July 12, 2026. Architecture lives in `PLANNING.md`. The
parked axis-schema experiment lives in `COA_AXES.md`.

Everything here was measured on FDA's own public data, not inferred.

---

## 1. What is actually in FDA's COA catalog

54 conditions. 7 ever qualified. Nothing since 2020.

Dated activity across all 54 COAs:

| Period | COAs | Note |
|---|---|---|
| 2011–2016 | 29 (53%) | |
| 2017–2020 | 25 (46%) | including 2019, the busiest year on record |
| **2021–2026** | **0** | |

The COA Compendium — FDA's only source linking a disease to an endpoint
to the drug approved using it — was last published June 2021. It
compiles work already done, and has no update mechanism; it was compiled
by hand, once.

Absent from the catalog entirely: breast cancer, ovarian, cervical,
endometrial, uterine, prostate, colorectal, pancreatic. Myocardial
infarction. Endometriosis, preeclampsia, postpartum depression,
menopause, osteoporosis.

The entire oncology catalog is five entries: `Cancer`, `NSCLC`,
`SCLC`, `Renal cell carcinoma`, `Plexiform neurofibroma`.

---

## 1a. The submissions pipeline stalls at the first stage

The submissions resource holds 72 COAs at every stage of qualification.
Grouped by stage, the distribution is top-heavy at the entry point:

| Qualification stage | Count |
|---|---|
| Letter of Intent — Accepted | 53 |
| Letter of Intent — Not Accepted | 9 |
| Qualification Plan — Accepted | 3 |
| Qualification Plan — Not Accepted | 2 |
| In legacy process | 3 |
| Withdrawn | 1 |
| Other single-stage entries | 1 |

53 of the 72 submissions — roughly three quarters — sit at "Letter of
Intent — Accepted," the first gate, having gone no further. Only a
handful ever reach a Qualification Plan, and 7 in total have completed
qualification (§1). This is consistent with the document shape in §10
(only 3 Full Qualification Packages exist) and with the program's own
description of being under-resourced: the pipeline accepts letters of
intent but rarely carries them through. The bottleneck is at the start,
not the finish.

---

## 2. FDA has the drug and not the endpoint

FDA knows tamoxifen treats breast cancer: it is on the approved label
(NDA021807) and coded in RxNorm (MeSH D001943). Both of FDA's own
systems say so.

And FDA has no qualified instrument to measure a breast cancer trial's
outcomes. Measured: 738 approved drug applications for breast cancer,
180 corroborated by both independent routes, and zero COAs.

The drug exists. The endpoint does not.

---

## 3. FDA's sources track qualification, not use

FDA's four sources track qualification. None tracks use.

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

The KCCQ is a primary endpoint in 117 trials — tirzepatide,
mavacamten, aficamten. It is widely used infrastructure.

Two qualified COAs have never been a primary endpoint in any trial; one
appears in no trial at all. Meanwhile the two most-used instruments in
the catalog were never qualified — the Short Physical Performance
Battery (1,710 trials, 356 primary endpoints) sits in the submissions
pile. And 50 of 80 catalog instruments appear in zero trials.

Nothing in any FDA source distinguishes any of these from any other;
they are all on the same list, described the same way.

(Caveat: the search is text-based and over-returns, so the counts are
directional, not exact. The shape is consistent across the catalog.)

---

## 4. A qualified COA was not used in the approval it might have carried

**Tezspire (tezepelumab)** — approved for asthma, December 2021.

FDA has a qualified asthma COA: DDT COA #000006, the Asthma Daytime
Symptom Diary (ADSD) — six items, scored 0 to 10, developed by C-Path's
PRO Consortium.

NAVIGATOR, tezepelumab's pivotal Phase 3, registered as a key secondary
endpoint "Change from baseline in Asthma Symptom Diary."

It is a different instrument. The ASD used in NAVIGATOR is ten items,
scored 0 to 4, from Globe et al 2015 — different developer, item count,
and scale.

Confirmed by the registry itself: searching outcome text for "Asthma
Symptom Diary" returns 22 trials; "Asthma Daytime Symptom Diary" returns
8 — different searches, different trials. If they were one instrument
the searches would collide.

So FDA qualified an asthma diary, a sponsor ran the pivotal trial with a
different, unqualified diary, and FDA approved the drug — and no FDA
source records any of it.

(A string matcher called this a hit; verification against the
psychometric papers caught it. That is why `endpoint_search` returns
verbatim text and never a boolean.)

---

## 5. condition_resolver: 53 of 54 (98%)

Validated by hand against the entire FDA COA catalog — not sampled,
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
Context of Use is "patients undergoing all forms of surgery and
anesthesia" — not a population. No vocabulary names it and no trial
registers it. FDA declined the COA at Letter of Intent for psychometric
reasons (a composite score "not sufficiently well-defined for regulatory
use"). The Disease/Condition field holds a clinical context, not a
condition.

---

## 6. FDA's condition field is written in trial-enrollment language

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
"Duchenne or Becker"). A COA exists to be used in a trial, so the field
speaks the registry's language.

A keyword approach gets this wrong: it would map "Non-Cystic Fibrosis
Bronchiectasis" to "bronchiectasis" and pull in the cystic fibrosis
patients FDA deliberately excluded. The exclusion is not noise in the
name; it is the trial design.

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

7 conditions have no parent in any source — and they are exactly the
five trial populations, the guidance-defined construct, and the
non-condition. That is a category fact, not a coverage gap: a trial
enrollment definition has no taxonomic parent because it is not the kind
of thing that has one.

---

## 7a. A shared parent is not enough — the false-sibling problem

Breadth across six taxonomies gives sensitivity: it finds every
relationship any source records. But a naive "they share a parent, so
they are siblings" rule finds relationships that are not real.

The case that exposed it: Gaucher disease surfaced cystic fibrosis as a
sibling. They are not clinically related. What they share is a single
SNOMED parent — "Autosomal recessive hereditary disorder" — an
inheritance-pattern grouping, not a disease family. By the same logic
every recessive disease would be a sibling of every other.

The discriminator is published in SNOMED itself: a real disease concept
carries defining attributes (finding site, associated morphology, and so
on); a pure grouper carries none.

| Shared parent | Defining attributes | Verdict |
|---|---|---|
| Heart failure | 3 | real disease family |
| Malignant neoplasm of lung | 2 | real disease family |
| Autosomal recessive hereditary disorder | 0 | grouper |

So the rule: a sibling that rests only on a zero-attribute grouper is
not surfaced. This keeps congestive/chronic heart failure (shared parent
"Heart failure," defined) and drops Gaucher/cystic fibrosis (shared
parent a grouper). It is a categorical test — the presence or absence of
a concept model, not a tuned threshold — and it is the hierarchy's
answer to specificity: breadth finds the candidates, the
defining-attributes gate removes the false ones. Sensitivity from the
six sources; specificity from the gate.

---

## 7b. A shared parent is not the only false-sibling source — the vote must converge

The defining-attributes gate (§7a) removes siblings that rest on a
zero-attribute grouper. It does not, on its own, resolve a second class
of false sibling: one source asserting a relationship that several
others actively contradict.

The case: "lung cancer" surfaced cystic fibrosis as a sibling. Under the
hood, five sources voted — SNOMED, NCIt, ICD-10-CM, and MedDRA all
computed UNRELATED; only MeSH called them siblings, via the coarse
"Lung Diseases" grouping that lumps a carcinoma and a genetic disorder
together. The relation is read across sources, so the question is how
the votes resolve.

The original tiebreak sorted any structural relation ahead of
UNRELATED, so a single MeSH SIBLING beat four active UNRELATED votes.
The fix: count agreeing sources first. A relation that only one source
asserts cannot outweigh a majority of sources that looked and found no
link. UNRELATED computed by four sources is a signal, not silence —
distinct from NO_HIERARCHY (a source that does not carry the concept),
which is genuine silence and never counts as a vote.

| | Sources for SIBLING | Sources for UNRELATED | Verdict |
|---|---|---|---|
| lung cancer / cystic fibrosis | 1 (MeSH) | 4 | UNRELATED |
| congestive / chronic heart failure | (real, defined parent) | | SIBLING |

Verified against the known-good pairs: heart failure→chronic HF stays
CHILD, congestive→chronic stays SIBLING, small cell→NSCLC stays
SIBLING; only the false lung-cancer/CF sibling flips. §7a's gate and
this vote rule are complementary: the gate removes siblings built on a
grouper, the vote removes siblings built on a lone dissenting source.

---

## 8. Why the four sources cannot be connected as they stand

| Source | How it is maintained |
|---|---|
| COA Compendium | Hand-curated PDF, by CDER review division (34 of them), published June 2021, no update mechanism. FDA's own language: it "collates and summarizes" — collates, not integrates. |
| DDT Project Search | Live Salesforce/Aura app. Required a scripted capture; GUI clicking failed entirely. |
| COA submissions / qualified | Server-rendered HTML tables. |
| Drugs@FDA | Periodic bulk download + openFDA API. No disease field at all. |

Four sources, four update mechanisms, one of which is a hand-compiled
PDF refreshed every few years. These are systems that were built
separately, for separate purposes, and never shared a key — which is why
connecting them is data work, not a display change.

---

## 9. Drugs@FDA IS bridgeable (corrects the original spike)

The first version of this file concluded Drugs@FDA was structurally
unbridgeable. That conclusion was superseded.

Two independent routes, both confirmed on real data:

    route 1  ApplNo -> openFDA indications_and_usage (PROSE)
    route 2  ApplNo -> rxcui -> RxNorm may_treat -> MeSH -> the CUI (CODED)

Breast cancer: 738 applications, 180 found by both routes, 515 coded
only, 43 label only.

Agreement is corroboration; disagreement is a finding. And the
disagreement is informative:

  - Label-only includes Cardiolite — a cardiac imaging agent whose
    label mentions breast tissue attenuation. A false positive from the
    string match, visible only because the tool prints the indication
    text instead of a count.
  - Coded-only includes chlorambucil and cyclophosphamide. MED-RT says
    therapeutic use; the approved label does not name breast cancer.
    `may_treat` is broader than an approved indication.

(The coded route initially returned zero drugs for breast cancer. The
cause: MONDO's `xref_mesh` is empty for MONDO:0007254, while RxNorm
links 826 rxcuis to MeSH D001943. The data was on disk; the bridge was
missing — for the most common cancer in American women. Fixed by asking
UMLS directly, since UMLS is the metathesaurus.)

---

## 9a. A COA can be linked to the drug development it served

§3 showed FDA cannot see which of its COAs are *used*. The trial
registry can close part of that gap directly: a trial names both its
interventions and its outcome measures, so a single trial record ties a
drug to a COA — this trial tested empagliflozin AND used the KCCQ.

Run that link for the KCCQ (chronic heart failure's qualified
instrument):

| Drug | Trials using the KCCQ that tested it |
|---|---|
| empagliflozin | 18 |
| dapagliflozin | 14 |
| sacubitril/valsartan | 12 |
| mavacamten | 7 |
| finerenone, ferric carboxymaltose, enalapril | 6 each |

These are the modern heart-failure armamentarium. The KCCQ is not a
form sitting in a drawer — it is the instrument the pivotal trials of
these approved drugs measured with. That is the connection none of the
four resources hold: they record that the KCCQ was *qualified*; the
registry records that it was *used*, and by whom.

Stated precisely: this is co-occurrence — the drug was tested in a trial
that used the COA. It is not a claim that the COA drove the approval, or
was even the primary endpoint. Whether the COA figured in any approval is a
regulatory fact the registry does not carry and the tool does not
assert. The drugs are filtered to FDA-approved ones (via openFDA);
investigational and discontinued compounds are dropped, because "the
KCCQ was used in a trial of a drug that never reached market" does not
speak to the approved armamentarium. The honest tail remains visible:
single-trial, adjacent studies (a sleep drug in a heart-failure
population) appear at the bottom, labeled as what they are.

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

The shape matters more than the count. Only 3 Full Qualification
Packages exist. That is not a scraper failure — it is the program's
actual state; most projects stop at Letter of Intent.

And 4 of the 7 qualified COAs have no Full Qualification Package posted
at all — including the KCCQ, the most-used COA in the catalog. Its
qualification evidence is not public. The posting is inconsistent: some
COAs expose FDA's internal reviews, some expose the requestor's package,
and the most-used one exposes neither.

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
gitignored; the scripts are the record.

---

## 12. The COA-number bridge (CONFIRMED)

Three sources share the DDT COA number, spelled differently in each.
`normalize_coa_keys.py` extracts a canonical 6-digit key.

- ddt_projects.csv: 150 distinct COA numbers (of 231 rows; the other 81
  are non-COA drug development tools — biomarkers, animal models)
- coa_submissions.csv: 71 — **100% match a DDT project**
- qualified_coas.csv: 7 — **100% match a DDT project**
- submissions & qualified: 0 overlap — disjoint by design
- in DDT but neither COA file: 72 — projects the public COA pages do
  not show

---

## 13. Inactive SNOMED codes silently break relation lookups

The relation engine reads is-a structure from SNOMED codes held in the
curated index (`cui_code_index.json`). Some of those codes were
inactive — retired concepts that the current SNOMED release no longer
carries a hierarchy for. An inactive code does not error; it returns no
parents and no children, so every relation computed from it comes back
empty, and a condition with a real place in the hierarchy reads as
having none.

24 catalog conditions were affected, heart failure among them
(inactive 155374007 → active 84114007). Each was repointed to the
active concept, verified by name against the current US edition. The
class is broader than the 24 fixed here: any CUI whose index entry
predates a SNOMED retirement can carry a stale code. The durable fix is
at index-build time — prefer the active concept when UMLS returns both —
and is noted for a later pass; tonight's repoints correct the catalog
conditions the demo touches.

A second, related fault: `code_in` consulted the relation cache before
the curated index, so even after a code was corrected the stale cached
code shadowed it. `code_in` now reads the curated index first and falls
to the cache only for CUIs the index does not carry.

---

## 14. Qualified and in-process COAs must be distinguished at display

A COA in the submissions resource is a proposed instrument at some stage
of qualification; only a qualified COA has cleared the bar (§1a, §12).
The data carries the distinction cleanly (every entry has a `qualified`
flag and a stage), but the display logic did not honor it, in two
places:

- The orchestrator treated any own-COA as "this condition has a COA,"
  so a condition whose only COA is an in-process submission (e.g. small
  cell lung cancer, #000133 at Letter of Intent) both suppressed the
  neighbor search and then displayed an unqualified instrument as if it
  were the answer. A condition now counts as having its own COA only
  when that COA is qualified; otherwise it falls through to the
  neighbor search, exactly as if it had none.
- Neighbor COAs were not filtered the same way, so a search could
  surface a *related* condition's in-process submission. The
  qualified-only rule now applies to own and neighbor COAs alike — an
  in-process submission is never surfaced as any condition's answer.

This is a display-layer finding, not a data-layer one: the sources are
honest about qualification status; the tool now is too. Note the effect
on breadth — roughly 35 of the catalog conditions have only in-process
COAs of their own (consistent with §1a's pipeline stall), so honoring
the flag moves most of them to a neighbor answer or an honest
"no qualified COA here."

---

## 15. The catalog view must match by identity and hierarchy, not text

The list/search view (`list_coas`) originally matched on substring. That
reproduces the Milliman failure directly: "small cell lung cancer" is a
substring of "non-small cell lung cancer," so a search for one returned
the other — two distinct diseases, different treatment, conflated by
text.

Exact-CUI matching was tried and is also wrong, in the opposite
direction: it strips every subtype. "Heart failure" (C0018801) stops
matching the KCCQ, which is filed under "Chronic Heart Failure"
(C0264716, a child); "non-small cell lung cancer" drops "metastatic
non-small cell lung cancer" (C0278987). A different CUI is not a
non-match — it is a hierarchical neighbor. Exact identity is the same
error as substring, just failing closed instead of open.

The catalog view now does what the rest of the system does: resolve the
query to an identity, then match each row by the relationship the
vocabularies record — exact, parent, child, sibling — and label each
result with that relationship. "Heart failure" surfaces the KCCQ marked
[child]; "small cell lung cancer" surfaces NSCLC-SAQ marked [sibling],
attributed to non-small cell, never asserted as small cell's own
qualified COA. The relationship is not decoration; it is the mechanism
that replaces a synonym list, and the label is how the reader sees why a
row surfaced and whose COA it actually is.

Non-disease queries (an instrument name, a concept word like "walk")
do not resolve to a condition and fall through to substring — the
correct behavior for a term that is not a disease. Typo handling is a
front-end concern, not a backend match rule.

---

## 16. Two operational findings from wiring identity into the catalog view

**The resolver requires the mondo context.** `condition_resolver.resolve`
reads `context["mondo_terms"]`, built once by `load_sources()`. Called
with an empty context it raises `KeyError('mondo_terms')` — not a
resolution failure, a crash — on roughly 90 of 228 catalog disease
names. This was a caller error (an empty context passed in), not a
resolver defect, but it is a fragility worth noting: the resolver
assumes a fully-built context and does not fail gracefully without one.
With the context built correctly, 165 of 228 names resolve; the 63 that
do not are almost entirely trial populations and non-disease strings
(§6) — "Bowel prep," "Forehead lines," the seizure-disorder subtypes —
which correctly have no single disease identity.

**Relation lookups must be warmed, not computed live.** `relate()` serves
SNOMED, ICD-10-CM, NCIt, and MedDRA from local indexes, but MeSH falls
through to the live UMLS API with a rate-limit pause. A catalog search
that calls `relate()` across every row hits that live path for every
uncached MeSH code and appears to hang. The relation cache is designed
to be pre-warmed (the orchestrator relies on exactly this); warming the
catalog's condition pairs once populates it, after which search is
local and instant. This mirrors the existing pattern — the disease→CUI
map and the COA cache are both built once, offline, for the same reason.
