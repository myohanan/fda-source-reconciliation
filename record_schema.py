"""
disease_schema.py
-----------------
Rare Disease Pre-Competitive Endpoint Library
Independent Women's Center for Better Health

Core data schema for the Rare Disease Pre-Competitive Endpoint
Library. Every agent reads from and writes to this schema.
Changes to this file affect every downstream agent.

The schema includes a consolidated "calibration" block (see
create_empty_calibration_block) that is the single home for
calibration signals. It holds only what a SINGLE run produces --
technical failures ("could not get it") and content errors ("it is
wrong"). The two cross-run drift classes (deterministic drift
between releases, generative drift across runs) are not here; they
are assembled at fleet level by the calibration collector from the
comparator output and the Delphi JSONs. Keeping them out keeps this
a true per-run process-health record.
"""

from datetime import date
from enum import Enum
from typing import Any

SCHEMA_VERSION: str = "3.3"


class Category(Enum):
    # Present in the FDA Surrogate Endpoint Table. Discrete
    # disease-to-endpoint mapping.
    ONE = "1"
    # At least one COMPLETED disease-specific human clinical trial
    # confirmed in ClinicalTrials.gov (and not in the FDA table).
    TWO = "2"
    # At least one REGISTERED or ongoing disease-specific human trial;
    # no completed trials.
    THREE = "3"
    # No FDA surrogate endpoint, no completed trial, and no registered
    # or ongoing trial. Endpoint generation suppressed. Note: category
    # is a function of FDA-table presence and trial status ONLY. Gene
    # identification and biology characterization are NOT category
    # inputs -- many rare diseases are non-genetic yet have trials.
    FOUR = "4"


class EndpointType(Enum):
    """
    Two endpoint categories for rare disease accelerated approval
    frameworks. Both are authorized under 21 USC 356(c)(1)(A).
    All endpoints must be pre-specified in the clinical trial protocol.
    Post-hoc analyses are excluded regardless of endpoint type.

    BIOCHEMICAL_SURROGATE: a pre-specified measurable biological marker
    in blood, CSF, urine, or tissue that predicts clinical benefit.
    Includes enzyme activity, substrate levels, protein expression,
    and biomarker concentrations. Must be designated as a primary or
    pre-specified secondary endpoint in the trial protocol.
    Corresponds to what the FDA Surrogate Endpoint Table currently
    contains.

    NON_BIOCHEMICAL: all other pre-specified endpoints explicitly
    authorized under 21 USC 356(c)(1)(A) as intermediate clinical
    endpoints measurable earlier than irreversible morbidity or
    mortality. Includes but is not limited to: physiological measures
    (muscle strength, respiratory capacity, nerve conduction, cardiac
    function), radiographic findings, functional outcomes (improvement,
    stabilization, decreased rate of decline), patient-reported
    outcomes, pharmacodynamic measures, composite endpoints, functional
    scales (ALSFRS-R, CHOP-INTEND, HINE, six-minute walk, FVC, SF-36,
    PROMIS), and any other pre-specified measure relevant to patient
    status. This category is explicitly authorized by statute and
    largely absent from the FDA Surrogate Endpoint Table.
    Post-hoc analyses are excluded.
    """
    BIOCHEMICAL_SURROGATE = "BIOCHEMICAL_SURROGATE"
    NON_BIOCHEMICAL = "NON_BIOCHEMICAL"


class GradeLevel(Enum):
    HIGH = "High"
    MODERATE = "Moderate"
    LOW = "Low"
    VERY_LOW = "Very Low"


class GeneConfidence(Enum):
    # ClinGen Definitive classification confirmed
    CONFIRMED = "CONFIRMED"
    # ClinGen Strong or Moderate classification
    HIGH = "HIGH"
    # Gene identified in Orphanet; no ClinGen classification available
    LOW = "LOW"
    # No gene resolved by the system. This does NOT drive category
    # (category depends on FDA table + trial status only); it feeds the
    # gene_resolution_worklist for manual review.
    NONE = "NONE"


def create_suppression_record(
    agent_name: str, reason: str, evidence_threshold: str
) -> dict[str, Any]:
    """Create a standardized agent suppression record."""
    return {
        "agent": agent_name,
        "suppression_reason": reason,
        "evidence_threshold_for_reactivation": evidence_threshold,
        "date_of_review": str(date.today()),
    }


def create_empty_calibration_block() -> dict[str, Any]:
    """
    Create the empty per-run calibration block.

    ONE consolidated home for the calibration signals a single run
    produces, read by the (future) collector. The spine is the
    failure CLASS; the grouping within each class encodes SHAPE (how a
    signal aggregates). The two classes here are the two a single run
    can produce:

      technical_failures -- "could not get it." Infrastructure: API /
        parse / unreachable / weaker-filter fallback / pagination
        shortfall. Recorded as a rate, never escalated. A rising rate
        is the signal that drives an architectural decision (e.g.
        abandon a live API and consume static baseline files instead).
        Reported BY SOURCE so the decision is per-pipe.
          by_source     -- per-run source-health: an outage or
                           parse/staleness condition that hits the
                           whole run at once (one data source down
                           affects every disease). Each carries the
                           live-vs-fallback / parse-ok signal for that
                           source. PubMed additionally carries the
                           computed fetch-failure and no-abstract
                           rates promoted out of excluded_pmids.
          by_model_call -- per-item rate / per-disease binary: a model
                           call that could not return a usable verdict
                           after retries. Sub-typed where the cause
                           splits, because different causes point at
                           different fixes (a flaky model endpoint vs
                           an upstream retrieval that returned nothing
                           to review).

      content_errors -- "it is wrong." A hallucinated citation, an
        out-of-set PMID, a stripped-but-cited pipeline error, an
        abstract that contradicts a claim. ZERO tolerance, counted
        separately, never blended into any technical rate. Escalation
        happens upstream (citation integrity / claim verification);
        these counts are mirrored here only so the fleet hallucination
        and contradiction rates are queryable in one place.

    structural_signals -- per-disease "nothing to verify" binaries.
      Not a failure and not an error: a flag that a run produced an
      empty thing a populated thing was expected (a Category 1-3 entry
      whose framework carried no endpoints to verify, no citations to
      check, or zero retrieved articles to grade). Surfaced because
      "nothing checked" must never be read as "verified clean."

    miscategorization_signals -- the two silent failures where an
      infrastructure problem produces a wrong CONTENT outcome (a wrong
      category) with no signal in either lane today. Slots reserved
      here now; the detectors that set them are rewritten with their
      agents (disease_resolution_agent).

    gene_resolution_worklist -- a valid-outcome backlog (not a failure,
      not an error): diseases for which the system produced no gene
      mapping (GENE_NOT_RESOLVED). The system cannot tell a genuinely
      non-genetic disease from a genetic one whose gene it missed, so
      each is flagged for human adjudication rather than labelled. The
      collector assembles the named worklist across the run.

    Every value starts empty/zero/None. The block is the home; the
    writers are separate per-file changes.
    """
    return {
        "technical_failures": {
            "by_source": {
                "pubmed": {
                    # per-run source-health
                    "id_retrieval_shortfall": None,
                    "layer3_fallback": None,
                    # computed rates promoted out of excluded_pmids
                    # (raw rows stay in evidence.pubmed_excluded_pmids
                    # for audit; these are the rates the collector
                    # aggregates and that drive the live-API decision)
                    "fetch_failure_rate": None,
                    "fetch_failure_count": None,
                    "no_abstract_rate": None,
                    "no_abstract_count": None,
                    "fetch_attempted_count": None,
                },
                "orphadata_epidemiology": {
                    "data_availability": None,
                    "stale_warning": None,
                },
                "orphadata_natural_history": {
                    "data_availability": None,
                    "stale_warning": None,
                },
                "orphadata_nomenclature": {
                    # API/local-snapshot drift. The live Orphanet API
                    # supplied the disease name in Step 1, but the
                    # local nomenclature snapshot did not contain this
                    # ORPHA ID (resolution_status
                    # NOMENCLATURE_NO_LOCAL_MATCH). Not a blocker --
                    # the entry proceeds on the API name. A rising
                    # rate is the signal that the local snapshot is
                    # stale and should be refreshed. Per-disease
                    # binary; the collector assembles the named list
                    # of drifted ORPHA IDs across the run.
                    "no_local_match": None,
                },
                "fda_table": {
                    "table_source": None,
                    "stale_warning": None,
                },
                "fda_approval": {
                    # Drug-approval database load health. Present
                    # (non-None) only when the shared orphan-drug
                    # file failed to load; the disease degrades
                    # (approval status UNKNOWN) rather than halting.
                    # A rising rate means the shared file is broken
                    # for the whole run.
                    "load_error": None,
                },
            },
            "by_model_call": {
                "claim_verification": {
                    "unverified_count": None,
                    "unverified_rate": None,
                    "unverified_api_count": None,
                    "unverified_no_abstract_count": None,
                },
                "citation_integrity": {
                    "unverified_count": None,
                    "unverified_rate": None,
                    "unverified_unreachable_count": None,
                    "unverified_unparseable_count": None,
                },
                "endpoint_plausibility": {
                    "unverified_model_failure": None,
                },
                "endpoint_evidence_filter": {
                    "fallback_rate": None,
                    "batches_fallback": None,
                    "articles_retained_unfiltered": None,
                },
                "generative_agent": {
                    "generation_truncated": None,
                    "generated_from_fallback": None,
                    "malformed_endpoint_count": None,
                    # Count of generated endpoints whose endpoint_type
                    # was missing or invalid from generation and
                    # defaulted to NON_BIOCHEMICAL. Written additively
                    # by the orchestrator (v3.23+); reserved here so
                    # the documented home lists it and it initializes
                    # to None on a suppressed generative run.
                    "defaulted_endpoint_type_count": None,
                },
                "category4_supplementary": {
                    "retrieval_failed": None,
                    "relevance_filter_applied": None,
                    "no_abstract_count": None,
                },
            },
        },
        "content_errors": {
            "hallucination_count": None,
            "out_of_set_count": None,
            "pipeline_error_count": None,
            "contradiction_count": None,
        },
        "structural_signals": {
            "no_endpoints_to_verify": None,
            "no_framework_citations": None,
            "challenge_zero_articles": None,
        },
        "miscategorization_signals": {
            # Infrastructure failure -> wrong category, silent today.
            # Detectors are rewritten with their agents.
            "gene_resolution_file_load_degraded": None,
        },
        "gene_resolution_worklist": {
            # A VALID-OUTCOME backlog, not a failure and not a content
            # error: the system produced no specific gene mapping
            # (resolution_status GENE_NOT_RESOLVED). This is one of two
            # situations the system CANNOT distinguish at resolution
            # time, which is exactly why the entry is flagged for a
            # human rather than labelled:
            #   1. No genetic cause exists -- the disease is genuinely
            #      non-genetic (autoimmune, infectious, toxic, other).
            #      The system is correct; eventually this earns a
            #      positive non-genetic classification.
            #   2. A genetic cause exists but was not resolved against
            #      the current reference data (missing MONDO, unmapped
            #      gene, edge case). This one needs a manual hardcode.
            # The binary asserts neither bucket -- only "no mapping
            # produced, undetermined, flagged for human adjudication."
            # The disease already carries its own orpha_id and name, so
            # the collector assembles the named worklist across the run
            # from the diseases whose binary is True. The manual review
            # of that list sorts each entry into bucket 1 or 2.
            "gene_not_resolved": None,
        },
    }


def create_empty_disease_schema(
    orpha_id: str, disease_name: str
) -> dict[str, Any]:
    """
    Create an empty pipeline schema dict for one disease.

    Schema version 3.3: reserves the generative_agent
    defaulted_endpoint_type_count calibration slot. Version 3.2 added
    the consolidated per-run calibration block and removed the dead
    endpoints.endpoint_type field.
    """
    return {
        "metadata": {
            "orpha_id": orpha_id,
            "disease_name": disease_name,
            "schema_version": SCHEMA_VERSION,
            "pipeline_build_date": str(date.today()),
            "synonyms": [],
            "definition": "",
            "orphadata": {},
            "canonical_disease_object": {},
            "gene_lookup_result": {},
            "agents_run": [],
            "agents_suppressed": [],
        },
        "biology": {
            "report": {}
        },
        "evidence": {
            "pubmed_citations": [],
            "pubmed_total_found": 0,
            "pubmed_audit": {},
            "pubmed_excluded_pmids": [],
            "pubmed_layer3_audit": {},
            "pubmed_study_type_counts": {},
            "pico_components_used": [],
            "clinical_trials": [],
            "trials_total_found": 0,
            "fda_approval_history": {},
            "endpoint_map": {},
        },
        "endpoints": {
            "fda_found": False,
            "fda_matched_entry": None,
            "fda_patient_population": None,
            "fda_surrogate_endpoint": None,
            "fda_approval_type": None,
            "fda_table_section": None,
            "fda_match_rationale": None,
            "generated_framework": {},
        },
        "classification": {
            "category": None,
            "category_rationale": "",
        },
        "audit_trail": {
            "comparator_output": {},
            "endpoint_plausibility_output": {},
            "citation_integrity_output": {},
            "claim_verification_output": {},
            "evidence_quality_output": {},
            "human_review_required": False,
            "minority_positions_documented": [],
            "evidence_cutoff_date": "",
            "agents_run_count": 0,
            "agents_suppressed_count": 0,
            "case_reports_stripped": [],
            "case_reports_stripped_count": 0,
        },
        "calibration": create_empty_calibration_block(),
    }
