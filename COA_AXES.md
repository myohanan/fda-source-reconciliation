# COA_AXES.md — an axis schema for clinical outcome assessments

**Status: PARKED. Demonstrated on 3 instruments. Not validated.**

This is a research artifact, not a deliverable. It is written down
because it worked, and because the reasoning would otherwise be lost.

---

## 0. The problem it solves

Instrument identity cannot be resolved by name.

FDA's qualified asthma COA is the **Asthma Daytime Symptom Diary
(ADSD)**. The pivotal trial that got Tezspire approved (NAVIGATOR)
registered a key secondary endpoint reading *"Change from baseline in
Asthma Symptom Diary."*

Those are different instruments. It took reading two psychometric
papers to establish that. A string matcher called it a hit. It looks
like a hit. **Nothing about the output would have looked broken.**

The names are not the information. The structure is.

---

## 1. What broke, and why no regex fixes it

FDA's catalog holds instrument identity as free text, with English
connectives doing semantic work they cannot reliably do:

    Asthma Daytime Symptom Diary (ADSD) AND Asthma Nighttime
        Symptom Diary (ANSD)
            -> "and" joins TWO INSTRUMENTS

    Cutaneous Lupus Erythematosus Disease Area and Severity Index
        (CLASI) IN Systemic Lupus Erythematosus (SLE)
            -> "in" attaches a POPULATION to one instrument

    Hidradenitis Suppurativa Area AND Severity Index (HASI)
            -> "and" is INSIDE the instrument's name

Three uses of the same two words, three different structural meanings.
No parser over English syntax separates them, because **the grammar is
not carrying the information — the axes are.**

A rule was written and it over-fired: it split the CLASI's population
qualifier off as if it were an instrument, producing a phantom
"instrument" called *"in Systemic Lupus Erythematosus"* with 112
trials. That is the failure this schema exists to prevent.

---

## 2. The axes

Modeled on LOINC, which decomposes an observation into six orthogonal
axes (Component, Property, Time, System, Scale, Method) and composes
identity from them rather than looking it up. The genius is that
changing one axis yields a different but valid observation.

| Axis | LOINC analogue | What it holds |
|---|---|---|
| **CONCEPT** | Component | The patient experience measured — asthma symptom severity, HF symptom burden, itch |
| **REPORTER** | System | Who reports — PRO / ObsRO / ClinRO / PerfO / DHT |
| **RECALL** | Time | Momentary / twice-daily / daily / past-7-days / 4-week |
| **SCALE** | Scale | Ordinal 0–4, ordinal 0–10, 11-point, VAS, count |
| **STRUCTURE** | — | Item count; subscale composition |
| **POPULATION** | — | Context of use: condition + age + severity + setting |
| **STATUS** | — | LOI / QP / FQP / Qualified / Not accepted |

CONCEPT, REPORTER, RECALL, and SCALE are close to LOINC's own axes.
STRUCTURE, POPULATION, and STATUS are additions this domain forces.

---

## 3. The discrimination test

The case that broke string matching:

| | ADSD (FDA's qualified COA) | ASD (used in NAVIGATOR) |
|---|---|---|
| CONCEPT | asthma symptom severity | asthma symptom severity |
| REPORTER | PRO | PRO |
| RECALL | twice daily | twice daily |
| **SCALE** | **0 to 10** | **0 to 4** |
| **STRUCTURE** | **6 items** | **10 items** |
| Developer | C-Path PRO Consortium | Globe et al 2015 |

**Two axes separate them. Not the name.** SCALE and STRUCTURE.

CONCEPT, REPORTER, and RECALL are identical — which is exactly why the
names look alike and why a human reading only the name would confuse
them, as one did.

---

## 4. Where the axes are stated (verbatim, from the documents)

Every value below is a **stated fact**, extracted verbatim. Nothing is
inferred. Where a document does not state an axis, it is `NOT_STATED` —
never guessed.

### COA #000006 — ADSD (Full Qualification Package)

> STRUCTURE: *"The ADSD is a **six-item** daily measure of asthma
> symptom severity that assesses three core categories of asthma
> symptoms"*
>
> **AND ALSO:** *"an average score across all **seven items** ranging
> from 0 to 10"* / *"the **7-Item** ADSD scores"*
>
> SCALE: *"Respondents are required to rate the six symptoms at their
> worst during the respective timeframes using an **11-point**"* scale,
> *"ranging from **0 to 10**"*
>
> RECALL: *"The ADSD is intended for **twice daily** completion and
> comprises a morning diary ... and an evening diary"*

### COA #000008 — SMDDS

> STRUCTURE: *"The **16-item** SMDDS addresses nine different domains
> of MDD: negative emotions/mood (four items), anxiety (two items)..."*
>
> RECALL: *"The SMDDS uses a recall of **'Over the past 7 days'**"*

### COA #000009 — NSCLC-SAQ

> STRUCTURE: *"The NSCLC-SAQ consists of **seven items** assessing
> symptoms of NSCLC"*
>
> RECALL: *"The recall period is **one week** (worded as 'over the last
> 7 days')"*

---

## 5. THE FINDING THE AXES SURFACED — AND THIS IS THE POINT

The ADSD's own Full Qualification Package describes it as **six-item**
in one sentence and **seven-item** in another.

That is not a parse error. **It is version drift**, stated in FDA's own
document — an instrument that changed between development and
qualification.

**A name cannot hold that fact. An axis can.**

    STRUCTURE: 6 items  [FQP p.1, verbatim]
               7 items  [FQP p.4, verbatim]
               CONFLICT — versions, or an error in the document

A name-based system averages this away by never seeing it. The axis has
a slot for it, so the contradiction becomes VISIBLE — which is the same
principle as the near-miss log, the two-citation floor, and the
suppression gates: **surface disagreement, never smooth it.**

The axis value is therefore not a number. It is **a claim, with
provenance, and possibly a version** — exactly as an endpoint is.

---

## 6. Where the data lives

| Axis | Source | Coverage |
|---|---|---|
| REPORTER | catalog (`COA Type`) | **79 / 79** |
| STATUS | catalog | **79 / 79** |
| CONCEPT | LOI (`Concept of Interest`) | ~54 |
| POPULATION | Qualification Statement / LOI (`COU`) | ~54 |
| **STRUCTURE, SCALE, RECALL** | **Full Qualification Package** | **3** |
| STRUCTURE, SCALE, RECALL (fallback) | **the validation paper** | potentially all |

**Only 3 FQPs exist in the entire program.** So FDA's own packets are
the most authoritative source and the rarest one.

The fallback is the literature, and it works — confirmed on PubMed:

    ADSD  PMID 42159666  -> scale 0–10, daily
    ASD   PMID 26549745  -> **10 items**, twice daily, 7-day
          (Globe et al, "Psychometric Properties of the Asthma
           Symptom Diary (ASD)")
    KCCQ  PMID 41817207  -> **23 items**

That makes sense: **FDA does not define instruments. It qualifies
them.** An instrument is defined by its psychometric validation paper,
because that is what validation IS. Every validated instrument has one.

Extraction from ABSTRACTS is incomplete (the ASD's abstract gives item
count but not scale; the ADSD's gives scale but not item count). The
full text has both. So this is a document-reading problem with the same
discipline as `claim_verification`: extract what is STATED, verify it
appears verbatim, never infer.

---

## 7. Honest limits

**Three instruments is a demonstration, not a validation.** And three
is not a sample — it is the ENTIRE POPULATION of Full Qualification
Packages. "Will this generalize" is therefore unanswerable from FDA's
packets, permanently. There is nothing more to test on.

**The axis set is probably domain-shaped, not universal.** It held for
three PROs. It should be expected to bend on:

  - a **PerfO** — a six-minute walk test has no recall period and no
    response scale
  - a **DHT** — an accelerometer has no items
  - a **composite** — the KCCQ's Clinical Summary Score is composed of
    two subscale scores, which is a structure the STRUCTURE axis does
    not currently express

**Finding where the axes break is the real work**, and it has not been
done.

**And the schema does not populate itself.** STRUCTURE, SCALE, and
RECALL exist in FDA's documents for 3 of 79 COAs. Everything else
requires reading the literature.

---

## 8. Why this is parked

It is a research program, not a deliverable. It is genuinely
interesting and it is **not** the thing that gets FDA's attention.

The FDA-facing work is: resolve conditions, connect the four sources,
show what exists and what does not. That is built and it works.

This is the layer underneath — the one that would let the catalog be a
DATABASE rather than a webpage. FDA already mandates CDISC QRS
supplements, which declare an instrument's items and response codes as
a controlled standard. **The schema exists in FDA's ecosystem. FDA has
simply never applied it to its own program.**

That is the finding. The rest is a research question.

---

## 9. The broader idea this came from

A riff on LOINC as a general instrument for normalizing free-text
medical content — either additional axes, or multiple complementary
axis systems, each capturing a different medical vocabulary's concerns.

The insight this test supports: **the grammar of medicine is not the
grammar of English.** Free text collapses orthogonal facts into a
sentence, and no parser recovers them reliably, because the syntax was
never carrying the structure. Axes hold facts apart. And once facts are
held apart, **contradictions become visible instead of averaged away.**

That is the same principle as the near-miss log, the two-citation
minimum, and the suppression gates — applied to the vocabulary layer.

---

## 10. ADDENDUM — tested against 252 CDISC instruments

**Result: STRUCTURE holds. The rest is unproven. One prediction failed.**

### What CDISC/NCIt actually gives you, for 252 instruments

Free, machine-readable, on NCI EVS. Confirmed by pulling all 252:

  - **Item count, COUNTED from a declared list.** Zero retrieval
    failures. The ADSD's codelist C163384 has six symptom items as six
    separate concepts, plus a Total Score declared separately. That
    resolves the six-versus-seven contradiction in FDA's own Full
    Qualification Package: six ITEMS, seven VALUES if the derived total
    is counted. **A prose reader sees a contradiction. A declared list
    does not.**
  - **Item-level question text, verbatim.** C163818 carries "Please
    rate your difficulty breathing at its worst since you got up this
    morning." That is a far stronger discriminator than item count.
  - **Name variants, declared.** ADSD V1.0 / ADSD01 / ADSD Version 1.0
    / Asthma Daytime Symptom Diary V1.0 Questionnaire. **The
    name-variant problem this whole schema was invented to solve is
    simply answered by the terminology.**
  - **Versions.** 89 of 252 carry one. Version drift is a first-class
    fact, not an edge case.

Item-count distribution across 252: 1 to 299 items, 70 distinct values,
peaks at 6 / 10 / 15 / 25. **230 of 252 share an item count with
another instrument** -- so STRUCTURE alone is NOT identity, which is
exactly what a composition schema predicts. If item count were unique
it would just be a bad primary key.

### The prediction that failed

The ADSD's NCI definition reads:

> "A **six-item** **self-administered** questionnaire, developed by
> **Gater et al. in 2016**, that utilizes a **ten-point rating scale**
> to assess a patient's experience with core asthma symptoms during the
> **preceding day**."

Six axes in one sentence. It looked like a template, and the obvious
inference was that the axes are extractable at scale from NCIt's own
definitions.

**They are not.** Measured across all 252:

    STRUCTURE   18/252   ( 7%)
    REPORTER    20/252   ( 7%)
    RECALL       9/252   ( 3%)
    SCALE        2/252   ( 1%)
    DEVELOPER    0/252   ( 0%)

    212 of 252 instruments state ZERO axes.
    NOT ONE instrument states all five.

The ADSD is an outlier, not a pattern. **One good example is not
evidence, and this is the fifth time in this project that a prediction
made instead of a measurement was wrong.**

### A methodological error, recorded

The test read the definition of each instrument's CODELIST (C163384),
not of the INSTRUMENT CONCEPT (C163811) -- and the rich definition was
on the instrument. So the measurement may have been taken against the
wrong objects, and re-running it correctly would likely improve the
numbers.

It is recorded anyway, uncorrected, because the conclusion does not
change: **the axes were not shown to be extractable at scale, and I was
one step from saying they were.**

### Where this actually leaves the schema

**Proven:** STRUCTURE, as a counted axis, across 252 instruments.
**Available but untested:** item text, name variants, versions.
**Unproven:** SCALE, RECALL, REPORTER, CONCEPT, POPULATION as
extractable axes.

**And the practical finding stands on its own, independent of the
schema:** NCIt/CDISC already declares instrument identity -- name
variants, item counts, item text, versions -- as free, machine-readable
data, for 252 instruments. **The name-matching problem that broke the
COA usage search is already solved by a terminology FDA itself
mandates.**

### The KCCQ is not in it

Searched four ways. Not in the CDISC Questionnaire terminology, not in
the QRS terminology, not anywhere in NCIt.

  FDA QUALIFIED the KCCQ in 2020.
  It is a PRIMARY ENDPOINT in 117 trials -- tirzepatide, mavacamten,
      aficamten.
  It appears in 1,029 registered trials.
  FDA REQUIRES CDISC-formatted trial data.
  CDISC HAS NO CONTROLLED TERMINOLOGY FOR IT.

Meanwhile CDISC *does* have the ADSD -- 8 trials, never a primary
endpoint.

So the standardization tracks FDA's qualification program, not the
field's actual usage. Every sponsor running a KCCQ trial is mapping it
to SDTM by hand, independently, with no controlled terms.

### Next, if this is picked up again

  1. Re-run the definition test against the INSTRUMENT concepts, not
     the codelists.
  2. Test whether ITEM TEXT discriminates instruments that item count
     cannot -- 230 of 252 collide on item count, so this is the real
     question.
  3. Find where the axis set BREAKS. A PerfO has no recall period. A
     DHT has no items. A schema that fits everything explains nothing,
     and the breaks have not been looked for.
