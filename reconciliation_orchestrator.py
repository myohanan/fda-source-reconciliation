"""
orchestrator.py
---------------
Rare Disease Pre-Competitive Endpoint Library
Independent Women's Center for Better Health

Pipeline for the Rare Disease Pre-Competitive Endpoint Library.

run_pipeline processes one disease through a fixed, ordered
sequence of deterministic tools and bounded generative steps. The
deterministic layer decides; the generative steps propose. Each
step writes into a single per-disease schema that the next step
reads.

Pipeline sequence (run_pipeline):
  Step 1   -- Orphanet Agent: disease identity and prevalence.
  Step 2   -- Disease Resolution Agent: canonical object (identity,
              hierarchy, MONDO, disease class, genes).
  Step 3   -- Orphadata Agent: gene and epidemiology records.
  Step 4   -- PubMed Agent: PICO-Cochrane retrieval of evidence.
  Step 5   -- FDA Surrogate Endpoint Agent: FDA surrogate-table
              match (drives Category 1).
  Step 6   -- FDA Approval History Agent: orphan-drug approvals
              (degrades on a load failure, does not stop -- status
              sealed UNKNOWN and recorded for calibration).
  Step 7   -- ClinicalTrials.gov Agent: trials, title-primacy
              matched.
  Step 8   -- Biology Agent: informational biology (mechanism /
              definition) present-or-absent; not a category or
              endpoint input.
  Step 9   -- Category Assignment: research maturity (1-4) from
              trial status, assigned here -- not by any single
              agent upstream.
  Step 10  -- Category 4 Supplementary Evidence Agent (Category 4
              only).
  Step 11  -- Endpoint Evidence Filter Agent: pre-generation
              filter to endpoint-relevant articles.
  Step 12  -- Generative Agent: proposes endpoints and points at
              supporting articles by reference number (never
              authors a PMID).
  Step 13  -- Endpoint Plausibility Challenge Agent: adversarial
              surrogate-plausibility review of the proposed
              framework. Infrastructure failures are set aside as
              UNVERIFIED, not content verdicts. (The Challenge,
              Genetics, and Biology challenge agents once run at
              this stage have been retired: gene resolution is
              sealed upstream in the Disease Resolution Agent and
              biology status in the Biology Agent, both
              informational only and not load-bearing.)
  Step 14  -- Citation Integrity Agent: every cited PMID must be
              in the retrieved set.
  Step 15  -- Claim Verification Agent: each PMID verified
              against its abstract; unsupported PMIDs dropped.
  Step 16  -- Endpoint Placement Gate: deterministic count of
              surviving PMIDs per endpoint (>= 2 -> 3B, else
              excluded). This is where placement is decided.
  Step 17  -- Suppression Leak Gate: confirms nothing that was
              dropped reached placement (the one hard-stop escape
              check).
  Step 18  -- Comparator + Endpoint Recovery. Runs after the
              placement gate (16) and suppression-leak gate (17):
              the comparator's retention classifier diffs the
              prior release's placed endpoints against the CURRENT
              placement, which does not exist any earlier. A prior
              3B endpoint absent from the current generation for
              any non-evidence reason -- generative variance, or a
              supporting PMID merely not retrieved this run while
              NOT retracted -- is retained with its full prior
              endpoint object and recovered into the sealed
              placement. Only retraction or expression of concern
              removes a published endpoint; such an endpoint is
              NEVER recovered. Recovery restores a sealed prior
              decision without adjudicating, re-searching, or
              fabricating; it is invisible to the document agent
              and recorded in its own calibration category. Runs
              only when a prior release exists to diff against
              (run_comparator); on the first release there is
              nothing to retain from.
  Step 19  -- Evidence Quality Challenge Agent.
Then document_agent renders the placement the gate assigned.

run_delphi_mode runs the same release multiple times end to end to
measure inter-run consistency (process consensus, endpoint-count
consensus) against input variance -- the calibration instrument,
not part of a normal single-disease run.

Calibration, not per-item escalation: routine suppressions
(dropped citations, set-aside UNVERIFIED results) are recorded as
calibration signals read in aggregate across the fleet, not
escalated for individual human review. The suppression-leak gate is
the one condition that hard-stops.

PIPELINE_VERSION (from config) stamps the release onto every
schema's audit trail. Per-tool AGENT_VERSION constants version
independently; version history is maintained in Git, not in this
module.
"""

import json
import logging
import os
import time
from datetime import date
from typing import Any

from config import PIPELINE_VERSION
from disease_schema import create_empty_disease_schema
from orphanet_agent import get_disease_data
from disease_resolution_agent import resolve_disease
from pubmed_agent import search_pubmed
from fda_agent import check_fda_surrogate_endpoints
from fda_approval_agent import get_fda_approval_history
from clinicaltrials_agent import search_clinical_trials
from categorization_agent import assign_category
from generative_agent import generate_endpoint_framework
from document_agent import create_library_entry
from biology_agent import report_biology
from orphadata_agent import get_disease_context
from comparator_agent import compare_runs
from endpoint_recovery_splice import _run_endpoint_recovery
from endpoint_plausibility_challenge_agent import (
    challenge_endpoint_plausibility,
)
from endpoint_evidence_filter_agent import (
    filter_evidence_for_endpoints,
)
from endpoint_placement_gate import assign_placement
from suppression_leak_gate import check_suppression_leak
from citation_integrity_agent import verify_citations
from claim_verification_agent import verify_claims
from evidence_quality_challenge_agent import (
    challenge_evidence_quality,
)
from category4_pubmed_agent import search_category4_supplementary

logger = logging.getLogger(__name__)


def _strip_case_reports(
        articles: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    stripped = []
    kept = []
    for article in articles:
        if (article.get("is_case_report") or
                article.get("is_protocol")):
            stripped.append({
                "pmid": article.get("pmid"),
                "title": article.get("title", "")[:100],
                "study_type": article.get("study_type"),
                "reason": "stripped_before_generative_agent"
            })
        else:
            kept.append(article)
    return kept, len(stripped), stripped


def _pipeline_stop(schema: dict[str, Any],
                   reason: str,
                   step: str) -> dict[str, Any]:
    schema["audit_trail"]["pipeline_error"] = True
    schema["audit_trail"]["pipeline_error_reason"] = reason
    schema["audit_trail"]["pipeline_error_step"] = step
    schema["audit_trail"]["human_review_required"] = True
    schema["audit_trail"]["evidence_cutoff_date"] = str(
        date.today())
    schema["audit_trail"]["pipeline_version"] = PIPELINE_VERSION
    logger.error("PIPELINE STOP -- %s", reason)
    logger.error(
        "No category assigned. Human review required.")
    return schema


def _populate_calibration_block(
        schema: dict[str, Any]) -> dict[str, Any]:
    """
    Populate the per-run calibration block from signals the agents
    already wrote to the schema. Called once at finalization.

    PURELY ADDITIVE. Reads from the schema only; writes only into
    schema["calibration"]. Changes no pipeline behavior, gating,
    category, or document-suppression logic. The existing audit_trail
    calibration writes and agent output dicts are left untouched; this
    mirrors from them so the block is the one consolidated home the
    (future) collector reads.

    Signals that require an agent rewrite to expose a clean value are
    deliberately left None here and noted inline: the PubMed
    fetch-failure / no-abstract rates, the biology UNVERIFIED split,
    and the two miscategorization detectors. Re-deriving any of those
    here would risk disagreeing with the agent's own determination.
    """
    cal = schema.get("calibration")
    if not isinstance(cal, dict):
        # Old schema without the block; nothing to populate.
        return schema

    audit = schema.get("audit_trail", {}) or {}
    evidence = schema.get("evidence", {}) or {}
    endpoints = schema.get("endpoints", {}) or {}
    metadata = schema.get("metadata", {}) or {}
    category = schema.get("classification", {}).get("category")

    tf = cal["technical_failures"]
    by_source = tf["by_source"]
    by_model = tf["by_model_call"]

    # ---- by_source: pubmed (shortfall + layer3 fallback) ----
    # Read directly from the persisted pubmed audit in evidence, the
    # same single-source pattern as the fetch-rate read below. The
    # orchestrator no longer writes intermediate audit_trail copies of
    # these (the dual-write is retired): the calibration block is the
    # one home for the signal, and it reads the agent's persisted
    # output. id_retrieval_shortfall is present-or-absent in the audit,
    # so .get yields None when there was no shortfall (correct). The
    # layer3 fallback is recorded only when the agent flagged a heavy
    # fallback (layer3b_fallback_calibration), preserving the same
    # gated content the audit_trail copy used to carry.
    pubmed_audit = evidence.get("pubmed_audit", {}) or {}
    by_source["pubmed"]["id_retrieval_shortfall"] = pubmed_audit.get(
        "id_retrieval_shortfall")
    layer3_audit = evidence.get("pubmed_layer3_audit", {}) or {}
    if layer3_audit.get("layer3b_fallback_calibration"):
        by_source["pubmed"]["layer3_fallback"] = {
            "batches_total": layer3_audit.get("batches_total"),
            "batches_3b_fallback": layer3_audit.get(
                "batches_3b_fallback"),
            "track": layer3_audit.get("track"),
        }
    else:
        by_source["pubmed"]["layer3_fallback"] = None

    # Fetch-layer rates, routed from the value the pubmed_agent
    # computed (pubmed_agent v3.2) and Step 4 persisted to evidence.
    # Routed, not re-derived: the agent owns its exclusion vocabulary
    # and its fetch-attempt denominator, and computes these before
    # the Step 11 endpoint filter appends to excluded_pmids. The
    # rates are None on a zero-attempt (zero-result) run, which is
    # preserved here so "no fetch happened" stays distinguishable
    # from "fetched, nothing failed."
    fetch_cal = evidence.get("pubmed_fetch_calibration") or {}
    pm = by_source["pubmed"]
    pm["fetch_attempted_count"] = fetch_cal.get(
        "fetch_attempted_count")
    pm["fetch_failure_count"] = fetch_cal.get("fetch_failure_count")
    pm["fetch_failure_rate"] = fetch_cal.get("fetch_failure_rate")
    pm["no_abstract_count"] = fetch_cal.get("no_abstract_count")
    pm["no_abstract_rate"] = fetch_cal.get("no_abstract_rate")
    pm["not_returned_count"] = fetch_cal.get(
        "not_returned_count")
    pm["not_returned_rate"] = fetch_cal.get("not_returned_rate")

    # ---- by_source: orphadata (epidemiology + natural history) ----
    orphadata = metadata.get("orphadata", {}) or {}
    epi = orphadata.get("epidemiology", {}) or {}
    nh = orphadata.get("natural_history", {}) or {}
    stale = orphadata.get("orphadata_stale_warning")
    by_source["orphadata_epidemiology"]["data_availability"] = (
        epi.get("data_availability"))
    by_source["orphadata_epidemiology"]["stale_warning"] = stale
    by_source["orphadata_natural_history"]["data_availability"] = (
        nh.get("data_availability"))
    by_source["orphadata_natural_history"]["stale_warning"] = stale

    # ---- by_source: orphadata_nomenclature (API/local drift) ----
    # The live API supplied the name in Step 1; a missing local
    # nomenclature match (resolution_status NOMENCLATURE_NO_LOCAL_MATCH)
    # means the local snapshot lags the API. Per-disease binary; the
    # collector assembles the drifted ORPHA IDs across the run. Read
    # straight from the sealed resolution status -- no re-derivation.
    _res_status = (
        metadata.get("canonical_disease_object", {}) or {}
    ).get("resolution_status")
    by_source["orphadata_nomenclature"]["no_local_match"] = (
        _res_status == "NOMENCLATURE_NO_LOCAL_MATCH")

    # ---- gene_resolution_worklist (valid-outcome backlog) ----
    # GENE_NOT_RESOLVED is a valid outcome the system cannot sort into
    # "non-genetic disease" vs "genetic disease whose gene we missed";
    # the binary flags it for human adjudication. Read from the sealed
    # status; the disease carries its own name for the worklist.
    cal["gene_resolution_worklist"]["gene_not_resolved"] = (
        _res_status == "GENE_NOT_RESOLVED")

    # ---- by_source: fda_table (persisted at Step 5) ----
    by_source["fda_table"]["table_source"] = endpoints.get(
        "fda_table_source")
    by_source["fda_table"]["stale_warning"] = endpoints.get(
        "fda_table_stale_warning")

    # ---- by_source: fda_approval (drug-approval load health) ----
    # load_error is present only when the shared orphan-drug file
    # failed to load; the disease degraded (approval status
    # UNKNOWN) rather than halting. Surfaced so a broken shared
    # file shows as a fleet rate, not just per-disease.
    approval_hist = evidence.get("fda_approval_history", {}) or {}
    by_source["fda_approval"]["load_error"] = approval_hist.get(
        "load_error")

    # ---- by_model_call: claim_verification ----
    claim = audit.get("claim_verification_output", {}) or {}
    if not claim.get("suppressed"):
        cm = by_model["claim_verification"]
        cm["unverified_count"] = claim.get("unverified_count")
        cm["unverified_rate"] = claim.get("unverified_rate")
        cm["unverified_api_count"] = claim.get(
            "unverified_api_count")
        cm["unverified_no_abstract_count"] = claim.get(
            "unverified_no_abstract_count")

    # ---- by_model_call: citation_integrity ----
    cit = audit.get("citation_integrity_output", {}) or {}
    if not cit.get("suppressed"):
        ci = by_model["citation_integrity"]
        ci["unverified_count"] = cit.get("unverified_count")
        ci["unverified_rate"] = cit.get("unverified_rate")
        ci["unverified_unreachable_count"] = cit.get(
            "unverified_unreachable_count")
        ci["unverified_unparseable_count"] = cit.get(
            "unverified_unparseable_count")

    # ---- by_model_call: plausibility (single cause) ----
    # Only ONE UNVERIFIED cause (the model review could not
    # complete), so the orchestrator can route it from severity
    # directly -- no sub-typing needed and no re-derivation risk.
    plaus_sev = (audit.get("endpoint_plausibility_output", {})
                 or {}).get("severity")
    by_model["endpoint_plausibility"][
        "unverified_model_failure"] = (plaus_sev == "UNVERIFIED")

    # ---- by_model_call: endpoint_evidence_filter ----
    filt = audit.get("endpoint_evidence_filter_output", {}) or {}
    if not filt.get("suppressed"):
        ef = by_model["endpoint_evidence_filter"]
        ef["fallback_rate"] = filt.get("fallback_rate")
        ef["batches_fallback"] = filt.get("batches_fallback")
        ef["articles_retained_unfiltered"] = filt.get(
            "articles_retained_unfiltered")

    # ---- by_model_call: generative_agent ----
    # generative_agent v5.1 surfaces these at the top level of its
    # return, so generative_calibration now carries real values
    # rather than None. defaulted_endpoint_type_count is the
    # malformed-endpoint-type check re-homed into the generative
    # agent (it counts the endpoint_type values it had to coerce to
    # NON_BIOCHEMICAL); recorded here for calibration, never escalated.
    gen_cal = audit.get("generative_calibration", {}) or {}
    ga = by_model["generative_agent"]
    ga["generation_truncated"] = gen_cal.get("generation_truncated")
    ga["generated_from_fallback"] = gen_cal.get(
        "generated_from_fallback")
    ga["malformed_endpoint_count"] = gen_cal.get(
        "malformed_endpoint_count")
    ga["defaulted_endpoint_type_count"] = gen_cal.get(
        "defaulted_endpoint_type_count")

    # ---- by_model_call: category4_supplementary ----
    cat4 = evidence.get("category4_supplementary_evidence", {}) or {}
    if not cat4.get("suppressed"):
        c4 = by_model["category4_supplementary"]
        c4["retrieval_failed"] = cat4.get("retrieval_failed")
        c4["relevance_filter_applied"] = cat4.get(
            "relevance_filter_applied")
        c4["no_abstract_count"] = cat4.get("no_abstract_count")

    # ---- content_errors (mirror; escalation already upstream) ----
    # Counted separately and never blended into a technical rate. The
    # escalation to human review already happened in Steps 14/15;
    # these are mirrored here so the fleet hallucination and
    # contradiction rates are queryable in one place.
    ce = cal["content_errors"]
    if not cit.get("suppressed"):
        ce["hallucination_count"] = cit.get("hallucination_count")
        ce["out_of_set_count"] = cit.get("out_of_set_count")
        ce["pipeline_error_count"] = cit.get("pipeline_error_count")
    if not claim.get("suppressed"):
        ce["contradiction_count"] = claim.get(
            "red_contradiction_count")

    # ---- structural_signals ----
    ss = cal["structural_signals"]
    if not claim.get("suppressed"):
        ss["no_endpoints_to_verify"] = (
            claim.get("overall_verdict") == "NO_ENDPOINTS_TO_VERIFY")
    if not cit.get("suppressed"):
        ss["no_framework_citations"] = cit.get(
            "no_framework_citations")
    # Challenge zero-article retrieval miss is only meaningful for a
    # Category 1-3 disease: such an entry retrieving zero articles is
    # the suspicious case (a Category 4 with zero is unremarkable).
    # The count is read directly from the retrieved citation set, not
    # from any grading agent's output -- "did retrieval come back
    # empty" is a fact about retrieval, not about grading.
    total_articles = len(evidence.get("pubmed_citations", []) or [])
    if category in ("1", "2", "3"):
        ss["challenge_zero_articles"] = (total_articles == 0)

    # ---- miscategorization_signals ----
    miscat = cal["miscategorization_signals"]

    # gene_resolution_file_load_degraded: routed from the marker the
    # disease_resolution_agent v2.5 stamps onto the canonical object.
    # The agent's loaders distinguish a file that FAILED to load
    # (absent or unreadable) from one that loaded fine (even if
    # genuinely empty); file_load_degraded is True when any source
    # file consulted this run failed. This is a per-run-environment
    # signal -- a shared file missing on the run host depresses gene
    # confidence across every disease, tipping an unknown number from
    # Category 2/3 toward Category 4 -- so it is stamped identically on
    # every disease in a degraded run, which is what makes the
    # systematic case unmistakable at fleet scale. Routed, not
    # re-derived: the agent owns the file-load determination. Detection
    # only; no resolution value or category was changed by it.
    canonical = metadata.get("canonical_disease_object", {}) or {}
    miscat["gene_resolution_file_load_degraded"] = bool(
        canonical.get("file_load_degraded"))

    # ---- generative_variance_recovery (its own category) ----
    # Mirror the endpoint_recovery_agent's named output into the
    # calibration block under its OWN category, kept distinct from
    # content_errors, technical_failures, and the deterministic-drift
    # signals. Generative-variance recovery is NOT a content error and
    # NOT a technical failure -- it is the expected, healthy cost of
    # building at scale (a prior endpoint the current generation did
    # not re-surface, whose evidence was not retracted, carried
    # forward). Recorded so the recovery rate is queryable per disease
    # and, when the fleet collector is wired to read it, across the
    # fleet. Written under a guarded key so this does not assume the
    # schema predefined the slot (additive, like the rest of the
    # block). Absent on a run where recovery did not fire.
    #
    # The reason-split is fully present in the block: the per-endpoint
    # retention_reason rides inside each recovered_endpoints record
    # (copied wholesale below), and reason_distribution is the rollup
    # the recovery agent (v1.1) computed once -- COPIED here, not
    # re-derived, so the block cannot disagree with the agent's own
    # count. A block-only reader therefore has the reason-split without
    # reaching for the fuller audit_trail record.
    recovery_out = audit.get("endpoint_recovery_output")
    if isinstance(recovery_out, dict):
        cal["generative_variance_recovery"] = {
            "recovered_count": recovery_out.get(
                "recovered_count", 0),
            "skipped_count": recovery_out.get("skipped_count", 0),
            "prior_release_date": recovery_out.get(
                "prior_release_date"),
            "is_content_error": recovery_out.get(
                "is_content_error", False),
            "reason_distribution": recovery_out.get(
                "reason_distribution", {}),
            "recovered_endpoints": recovery_out.get(
                "recovered_endpoints", []),
        }

    return schema


# _run_endpoint_recovery has been extracted to
# endpoint_recovery_splice.py and is imported above. It is pure
# dict manipulation (no model/network/file I/O), so moving it to
# its own importable module lets both this orchestrator and the
# seam-test harness import the SAME shipped function -- the test
# now binds to the real splice rather than a contract copy. The
# Step 18 call site is unchanged.


def _document_blocked(schema: dict[str, Any]) -> tuple[bool, str]:
    """
    Check whether document generation should be blocked.

    Blocks ONLY on:
    1. suppression_leak_gate leaked True
       (a citation the pipeline suppressed reached the placed set --
       the suppression machinery itself failed). This is the one
       genuine failure: not a model error, not a per-disease content
       issue, but a broken guarantee that calls the whole generation
       process into question. Hard-stop and escalate.
    2. audit_trail human_review_required True
       (a challenge agent HIGH severity, or biology /
       plausibility FAIL -- a content judgment a human must review).

    DELIBERATELY DOES NOT BLOCK ON (v3.18):
    - citation_integrity_output REDs (hallucination / out-of-set /
      pipeline-error). These are healthy system behavior: the bad
      citation is caught and suppressed, and CANNOT reach the
      document by construction (it can never be claim-verified and
      placed). The suppression-leak gate above is the guarantee that
      this "cannot" actually holds. There is nothing for a human to
      resolve about a caught hallucination -- the system did exactly
      what it should -- so it is suppressed and recorded in the audit
      trail, not escalated. (The citation_integrity_agent no longer
      sets human_review_required either.)
    - claim_verification RED_CONTRADICTION. Likewise healthy: the
      contradicted PMID is dropped from the count and cannot be
      placed. Suppressed and recorded, not escalated. (Claim
      verification no longer emits FAIL on contradiction.)

    RED_NO_MENTION from claim verification has never blocked -- those
    PMIDs are dropped from citation counts by the placement gate,
    which the document agent reads.

    NOTE ON CALIBRATION: the suppressed-and-recorded events
    (hallucination, out-of-set, pipeline-error, contradiction) are
    recorded in this run's audit trail and calibration block. This
    clean orchestrator does not run a calibration workflow over them
    -- that is the separate calibration version of the pipeline. Here
    the events are recorded honestly for later calibration analysis;
    nothing in this orchestrator claims a live calibration system
    consumed them.
    """
    audit = schema.get("audit_trail", {})

    # 1. Suppression leak -- the one genuine failure. A citation that
    #    was suppressed reached the placed set the document renders.
    leak = audit.get("suppression_leak_output", {})
    if leak.get("leaked"):
        return True, leak.get(
            "reason",
            "Suppression leak detected -- a suppressed citation "
            "reached the placed set. Document hard-stopped; the "
            "generation process must be reviewed."
        )

    # 2. Human-review flag from a content challenge (challenge agent
    #    HIGH, biology / plausibility FAIL).
    if audit.get("human_review_required"):
        return True, (
            "human_review_required flag set -- a challenge agent "
            "flagged a content judgment for human review. "
            "Document suppressed."
        )

    return False, ""


def run_pipeline(orpha_id: str,
                 disease_name: str,
                 run_comparator: bool = False) -> dict[str, Any]:
    logger.info("=" * 60)
    logger.info("STARTING PIPELINE FOR: %s", disease_name)
    logger.info("Pipeline version: %s", PIPELINE_VERSION)
    logger.info("=" * 60)

    schema = create_empty_disease_schema(orpha_id, disease_name)
    schema["metadata"]["agents_run"] = []
    schema["metadata"]["agents_suppressed"] = []

    # -- STEP 1: Orphanet Agent --
    logger.info("STEP 1: Orphanet Agent")
    logger.info("-" * 40)
    orphanet_data = get_disease_data(orpha_id)
    if "error" not in orphanet_data:
        schema["metadata"]["agents_run"].append(
            "orphanet_agent")
        schema["metadata"]["disease_name"] = orphanet_data.get(
            "disease_name", disease_name)
        schema["metadata"]["definition"] = orphanet_data.get(
            "definition", "")
        schema["metadata"]["synonyms"] = orphanet_data.get(
            "synonyms", [])
        logger.info("\u2713 Orphanet agent completed")
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "orphanet_agent",
            "reason": orphanet_data.get("error"),
            "date": str(date.today())
        })
        logger.info("\u2717 Orphanet agent suppressed")

    orphanet_synonyms = (
        orphanet_data.get("synonyms", [])
        if "error" not in orphanet_data else []
    )

    # -- NAME VERIFICATION --
    if "error" not in orphanet_data:
        returned_name = orphanet_data.get(
            "disease_name", "").lower()
        queried_name = disease_name.lower()

        name_match = (
            queried_name in returned_name or
            returned_name in queried_name or
            any(syn.lower() in returned_name
                for syn in orphanet_synonyms[:5])
        )

        if not name_match:
            logger.warning("\u26a0 NAME MISMATCH:")
            logger.warning("  Queried: %s", disease_name)
            logger.warning(
                "  Returned: %s",
                orphanet_data.get('disease_name'))
            schema["audit_trail"][
                "name_mismatch_warning"] = True
            schema["audit_trail"][
                "name_queried"] = disease_name
            schema["audit_trail"][
                "name_returned"] = orphanet_data.get(
                "disease_name")
            return _pipeline_stop(
                schema,
                "Disease name mismatch: queried '%s' but "
                "Orphanet returned '%s'" % (
                    disease_name,
                    orphanet_data.get('disease_name')
                ),
                "name_verification"
            )
        else:
            logger.info(
                "\u2713 Name verification passed: %s",
                orphanet_data.get('disease_name'))

    # -- STEP 2: Disease Resolution Agent --
    logger.info("STEP 2: Disease Resolution Agent")
    logger.info("-" * 40)
    canonical = resolve_disease(orpha_id, disease_name)
    schema["metadata"]["canonical_disease_object"] = canonical
    schema["metadata"]["agents_run"].append(
        "disease_resolution_agent")

    gene_symbol = canonical.get("primary_gene")
    gene_list = canonical.get("gene_set", [])
    gene_confidence = canonical.get("gene_confidence", "NONE")
    is_polygenic = canonical.get("is_polygenic", False)

    gene_identified = canonical.get("gene_identified", False)

    logger.info(
        "\u2713 Disease resolved: %s / %s",
        canonical.get('disease_class'),
        canonical.get('lookup_strategy'))
    logger.info("  Confidence: %s", gene_confidence)
    if canonical.get("mondo_id"):
        logger.info(
            "  MONDO ID: %s", canonical.get('mondo_id'))

    if gene_list:
        if is_polygenic:
            logger.info(
                "  Genes: %s%s (%d total)",
                ', '.join(gene_list[:5]),
                '...' if len(gene_list) > 5 else '',
                len(gene_list))
        else:
            logger.info(
                "  Gene: %s (confidence: %s)",
                gene_symbol, gene_confidence)
    else:
        logger.info(
            "  No gene resolved by the system "
            "(recorded for the gene-resolution worklist)")

    # Surface the disease-resolution file-load degradation signal.
    # disease_resolution_agent stamps file_load_degraded onto the
    # canonical object when a shared source file (HGNC, ClinGen,
    # MONDO, nomenclature, etc.) failed to load this run. A degraded
    # load silently depresses gene confidence across the whole run --
    # a borderline gene that ClinGen would have upgraded lands LOW --
    # so gene_confidence on a degraded run must not be read as
    # authoritative. This is an INFRASTRUCTURE signal: recorded for
    # calibration (the calibration block already routes the flag into
    # gene_resolution_file_load_degraded), not escalated and not
    # gating, consistent with the two-lane rule. Logged here so the
    # degradation is visible at the decision point, not only in the
    # JSON.
    if canonical.get("file_load_degraded"):
        logger.warning(
            "  \u26a0 CALIBRATION: gene-resolution source file load "
            "degraded this run (%s) -- gene confidence may be "
            "systematically depressed; recorded for calibration, not "
            "escalated.",
            ", ".join(canonical.get("degraded_files", []))
            or "unspecified")

    # -- STEP 3: Orphadata Agent --
    logger.info("STEP 3: Orphadata Agent")
    logger.info("-" * 40)
    orphadata_data = get_disease_context(orpha_id)
    schema["metadata"]["orphadata"] = orphadata_data
    schema["metadata"]["agents_run"].append("orphadata_agent")
    epi = orphadata_data.get("epidemiology", {})
    nh = orphadata_data.get("natural_history", {})
    prev_count = len(epi.get("prevalence_data", []))
    onset = nh.get("average_age_of_onset", [])

    for _label, _block in (("epidemiology", epi),
                           ("natural history", nh)):
        if _block.get("data_availability") == "file_parse_error":
            logger.warning(
                "\u26a0 Orphadata %s file is present but could "
                "not be parsed (file_parse_error) -- section will "
                "be blank; investigate the file", _label)

    logger.info(
        "\u2713 Orphadata agent completed -- "
        "%d prevalence entries, onset: %s",
        prev_count,
        ', '.join(onset) if onset else 'Not available'
    )

    # -- STEP 4: PubMed Agent --
    logger.info("STEP 4: PubMed Agent")
    logger.info("-" * 40)

    gene_lookup_result = {
        "gene_symbol": gene_symbol,
        "gene_list": gene_list,
        "is_polygenic": is_polygenic,
        "confidence_level": gene_confidence,
        "sources_confirming": [
            canonical.get(
                "gene_source", "disease_resolution_agent")
        ]
    }

    pubmed_data = search_pubmed(
        disease_name,
        synonyms=orphanet_synonyms,
        gene_lookup_result=gene_lookup_result
    )
    if "error" in pubmed_data:
        logger.warning(
            "  PubMed failed -- retrying in 30 seconds...")
        time.sleep(30)
        pubmed_data = search_pubmed(
            disease_name,
            synonyms=orphanet_synonyms,
            gene_lookup_result=gene_lookup_result
        )

    if "error" in pubmed_data:
        return _pipeline_stop(
            schema,
            "PubMed agent failed after retry: %s" % (
                pubmed_data.get('error')
            ),
            "pubmed_agent"
        )

    schema["metadata"]["agents_run"].append("pubmed_agent")
    schema["evidence"]["pubmed_citations"] = pubmed_data.get(
        "articles", [])
    schema["evidence"]["pubmed_total_found"] = pubmed_data.get(
        "total_found", 0)
    schema["evidence"]["pubmed_audit"] = pubmed_data.get(
        "audit", {})
    schema["evidence"]["pubmed_excluded_pmids"] = pubmed_data.get(
        "excluded_pmids", [])
    schema["evidence"]["pubmed_layer3_audit"] = pubmed_data.get(
        "layer_3_audit") or {}
    schema["evidence"]["pubmed_study_type_counts"] = (
        pubmed_data.get("study_type_counts", {}))
    schema["evidence"]["pico_components_used"] = pubmed_data.get(
        "pico_components_used", [])
    # Persist the PubMed fetch-layer calibration (pubmed_agent v3.2).
    # The agent computes the fetch-failure / no-abstract rates over
    # fetch attempts from its own exclusion vocabulary, before any
    # downstream stage contaminates excluded_pmids. Stored here so the
    # calibration block reads the agent's authoritative value rather
    # than re-deriving it from the (later-appended-to) excluded list.
    schema["evidence"]["pubmed_fetch_calibration"] = (
        pubmed_data.get("fetch_calibration"))
    layer3_audit = pubmed_data.get("layer_3_audit") or {}
    logger.info(
        "\u2713 PubMed agent completed -- %d found, "
        "%d after filters",
        pubmed_data.get('total_found', 0),
        pubmed_data.get('articles_retrieved', 0)
    )
    logger.info(
        "  PICO components: %s",
        pubmed_data.get('pico_components_used'))
    logger.info(
        "  Layer 3 track: %s",
        layer3_audit.get('track', 'N/A'))

    # -- PubMed retrieval-degradation routing (calibration only) --
    # The PubMed agent can flag two distinct retrieval degradations.
    # Both were folded into pubmed audit["human_review_required"],
    # which the orchestrator never read -- so both died in the JSON.
    # Neither is escalated. They are INFRASTRUCTURE signals, not
    # content failures, and this system's uniform rule is: an
    # infrastructure problem (we could not get the information --
    # bad API call, parse error, pagination shortfall, weaker-filter
    # fallback) is set aside and RECORDED FOR CALIBRATION; it never
    # triggers an ad-hoc human review. Only a genuine content failure
    # (an abstract that contradicts a claim, a hallucinated citation)
    # ever stops a document. This mirrors the claim_verification_agent
    # YELLOW_UNVERIFIED treatment exactly: give it multiple tries, and
    # if the information cannot be retrieved, do not count it, do not
    # halt, do not flood human review -- record it so the rate is
    # visible per disease and queryable across the fleet (e.g. a
    # whole-library integrity readout). Specificity over sensitivity:
    # an unretrieved citation can only ever understate support, never
    # fabricate it.
    #
    #   id_retrieval_shortfall -- pagination retrieved fewer IDs than
    #     total_found, so the evidence base may be incomplete. We did
    #     not get all the information; recorded for calibration.
    #   layer_3_audit["layer3b_fallback_calibration"] -- a large
    #     fraction of Layer 3 batches fell back to the weaker
    #     deterministic 3B filter (typically transient API
    #     degradation). Evidence set is complete, filtered more
    #     permissively; recorded for calibration.
    _pubmed_audit = pubmed_data.get("audit", {}) or {}
    if _pubmed_audit.get("id_retrieval_shortfall"):
        _shortfall = _pubmed_audit["id_retrieval_shortfall"]
        # The shortfall is persisted in schema["evidence"]
        # ["pubmed_audit"] (Step 4 above) and read from there by the
        # calibration block at finalization. No intermediate
        # audit_trail copy is written (the dual-write is retired).
        logger.warning(
            "  \u26a0 CALIBRATION: PubMed ID-retrieval shortfall -- "
            "retrieved fewer IDs than reported (total_found=%s, "
            "retrieved=%s, short=%s). Recorded for calibration, not "
            "escalated; the evidence base for this disease may be "
            "incomplete.",
            _shortfall.get("total_found"),
            _shortfall.get("retrieved"),
            _shortfall.get("shortfall"))

    if layer3_audit.get("layer3b_fallback_calibration"):
        # The layer3 fallback is persisted in schema["evidence"]
        # ["pubmed_layer3_audit"] (Step 4 above) and read from there by
        # the calibration block at finalization, gated on
        # layer3b_fallback_calibration. No intermediate audit_trail
        # copy is written (the dual-write is retired).
        logger.warning(
            "  \u26a0 CALIBRATION: PubMed Layer 3 fell back heavily "
            "to the weaker 3B filter (%s of %s batch(es), track %s)."
            " Evidence set is complete but filtered more "
            "permissively; recorded for calibration, not escalated.",
            layer3_audit.get("batches_3b_fallback"),
            layer3_audit.get("batches_total"),
            layer3_audit.get("track"))

    # -- STEP 5: FDA Surrogate Endpoint Agent --
    logger.info("STEP 5: FDA Surrogate Endpoint Agent")
    logger.info("-" * 40)
    fda_data = check_fda_surrogate_endpoints(
        disease_name, synonyms=orphanet_synonyms
    )
    if "error" not in fda_data:
        schema["metadata"]["agents_run"].append("fda_agent")
        # The FDA agent seals its table-record content (found, matched
        # entry, surrogate, population, approval type, section,
        # rationale, all_matches) into one fda_table_record object.
        # The orchestrator routes it whole -- it does not relabel or
        # re-derive any field. Readers access
        # schema["endpoints"]["fda_table_record"]["fda_..."].
        schema["endpoints"]["fda_table_record"] = fda_data.get(
            "fda_table_record", {})
        # Persist the FDA table source-health signals (v3.12). These
        # were previously logged only, so the live-vs-fallback and
        # staleness signals died in the run log. The calibration block
        # reads them from here.
        schema["endpoints"]["fda_table_source"] = fda_data.get(
            "fda_table_source")
        schema["endpoints"]["fda_table_stale_warning"] = (
            fda_data.get("fda_table_stale_warning"))
        logger.info(
            "\u2713 FDA agent completed -- found in table: %s",
            fda_data.get("fda_table_record", {}).get("fda_found"))
        _fda_source = fda_data.get("fda_table_source", "live")
        if _fda_source != "live":
            logger.warning(
                "  \u26a0 FDA table source: %s (not live) -- "
                "the live fetch did not yield a usable complete "
                "table; the hardcoded baseline was used",
                _fda_source)
        if fda_data.get("fda_table_record", {}).get("fda_found"):
            logger.info(
                "  Surrogate: %s",
                fda_data.get("fda_table_record", {}).get(
                    "fda_surrogate_endpoint"))
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "fda_agent",
            "reason": fda_data.get("error"),
            "date": str(date.today())
        })
        logger.info("\u2717 FDA agent suppressed")

    # -- STEP 6: FDA Approval History Agent --
    logger.info("STEP 6: FDA Approval History Agent")
    logger.info("-" * 40)
    approval_history = get_fda_approval_history(
        disease_name,
        synonyms=orphanet_synonyms,
        gene_symbol=gene_symbol
    )
    schema["evidence"]["fda_approval_history"] = approval_history

    if approval_history.get("load_error"):
        # Load failure degrades, does NOT stop: FDA drug-approval
        # status is contextual, not category-driving. The disease
        # proceeds with approval status sealed as UNKNOWN
        # (has_approvals is None); the document renders "could not
        # be determined" (never "no approved therapies"). Recorded
        # to agents_suppressed with the load_error preserved so the
        # calibration collector can surface a named worklist -- a
        # broken SHARED file shows up as every disease flagged,
        # which the fleet rate makes visible without halting the
        # run one disease at a time.
        schema["metadata"]["agents_suppressed"].append({
            "agent": "fda_approval_agent",
            "reason": approval_history.get(
                "error", "approval status unknown"),
            "load_error": approval_history.get("load_error"),
            "date": str(date.today())
        })
        logger.warning(
            "\u26a0 FDA approval database load failure (%s) -- "
            "approval status UNKNOWN, degraded not halted; "
            "recorded for calibration",
            approval_history.get("load_error"))
    elif approval_history.get("has_approvals"):
        schema["metadata"]["agents_run"].append(
            "fda_approval_agent")
        logger.info(
            "\u2713 FDA approval history -- %d drug(s) found",
            approval_history.get('total_approved', 0))
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "fda_approval_agent",
            "reason": approval_history.get(
                "error", "No approved drugs"),
            "date": str(date.today())
        })
        logger.info(
            "\u2717 FDA approval history -- no approved drugs")

    # -- STEP 7: ClinicalTrials.gov Agent --
    logger.info("STEP 7: ClinicalTrials.gov Agent")
    logger.info("-" * 40)
    trials_data = search_clinical_trials(
        disease_name, orphanet_synonyms)

    if "error" in trials_data:
        return _pipeline_stop(
            schema,
            "ClinicalTrials agent failed after retries: %s" % (
                trials_data.get('error')
            ),
            "clinicaltrials_agent"
        )

    schema["metadata"]["agents_run"].append(
        "clinicaltrials_agent")
    schema["evidence"]["clinical_trials"] = trials_data.get(
        "trials", [])
    schema["evidence"]["trials_total_found"] = trials_data.get(
        "trials_retrieved", 0)
    logger.info(
        "\u2713 ClinicalTrials agent -- %d trials found",
        trials_data.get('trials_retrieved', 0))

    # -- STEP 8: Biology Agent --
    logger.info("STEP 8: Biology Agent")
    logger.info("-" * 40)
    biology_result = report_biology(
        orpha_id,
        schema["metadata"].get("disease_name", disease_name))
    schema["biology"]["report"] = biology_result
    schema["metadata"]["agents_run"].append("biology_agent")
    logger.info(
        "\u2713 Biology report: %s",
        biology_result["biology_status"])

    # -- STEP 9: Category Assignment --
    logger.info("STEP 9: Category Assignment")
    logger.info("-" * 40)

    # Trial relevance classification and the category partition are
    # sealed by the trials agent (title-primacy; disease_specific vs
    # multi_condition/basket; completed/registered split). The
    # orchestrator ROUTES the sealed counts and the
    # disease_specific-only nct id list -- it does not classify,
    # partition, or count. The classified trials (each tagged with
    # relevance_class) are already stored in
    # schema["evidence"]["clinical_trials"] above.
    schema["classification"]["relevant_trials_count"] = \
        trials_data.get("relevant_trials_count", 0)
    schema["classification"]["disease_specific_trials_count"] = \
        trials_data.get("disease_specific_trials_count", 0)
    schema["classification"]["multi_condition_trials_count"] = \
        trials_data.get("multi_condition_trials_count", 0)
    schema["classification"]["completed_relevant_trials_count"] = \
        trials_data.get("completed_relevant_trials_count", 0)
    schema["classification"]["registered_relevant_trials_count"] = \
        trials_data.get("registered_relevant_trials_count", 0)
    schema["evidence"]["relevant_trial_nct_ids"] = \
        trials_data.get("relevant_trial_nct_ids", [])

    logger.info(
        "  Trials: %d relevant (%d disease-specific, "
        "%d multi-condition/basket), %d completed, %d registered "
        "(disease-specific only drive category)",
        trials_data.get("relevant_trials_count", 0),
        trials_data.get("disease_specific_trials_count", 0),
        trials_data.get("multi_condition_trials_count", 0),
        trials_data.get("completed_relevant_trials_count", 0),
        trials_data.get("registered_relevant_trials_count", 0)
    )

    _fda_rec = fda_data.get("fda_table_record", {})
    fda_found = _fda_rec.get("fda_found", False)

    category_result = assign_category(
        found_in_fda_table=fda_found,
        surrogate_endpoint=_fda_rec.get("fda_surrogate_endpoint"),
        completed_trials_count=trials_data.get(
            "completed_relevant_trials_count", 0),
        registered_trials_count=trials_data.get(
            "registered_relevant_trials_count", 0),
    )
    category = category_result["category"]
    rationale = category_result["category_rationale"]

    schema["classification"]["category"] = category
    schema["classification"]["category_rationale"] = rationale
    schema["metadata"]["agents_run"].append(
        "category_assignment_agent")
    logger.info("\u2713 Category assigned: %s", category)
    logger.info("  Rationale: %s", rationale[:100])

    # -- STEP 10: Category 4 Supplementary Evidence Agent --
    logger.info("STEP 10: Category 4 Supplementary Evidence Agent")
    logger.info("-" * 40)
    if category == "4":
        cat4_result = search_category4_supplementary(
            disease_name=schema["metadata"]["disease_name"],
            synonyms=orphanet_synonyms,
            gene_symbol=gene_symbol
        )
        schema["evidence"][
            "category4_supplementary_evidence"] = cat4_result
        schema["metadata"]["agents_run"].append(
            "category4_pubmed_agent")
        supp_count = cat4_result.get("articles_retrieved", 0)
        case_report_count = cat4_result.get(
            "case_report_count", 0)
        protocol_count = cat4_result.get("protocol_count", 0)
        logger.info(
            "\u2713 Category 4 supplementary search complete "
            "-- %d articles retrieved", supp_count
        )
        if case_report_count > 0:
            logger.info(
                "  Case reports: %d", case_report_count)
        if protocol_count > 0:
            logger.info(
                "  Trial protocols: %d", protocol_count)
        if supp_count == 0:
            logger.info("  No supplementary evidence found")
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "category4_pubmed_agent",
            "reason": (
                "Category %s -- supplementary search "
                "only runs for Category 4" % category
            ),
            "date": str(date.today())
        })
        schema["evidence"][
            "category4_supplementary_evidence"] = {
            "suppressed": True,
            "reason": "Category %s -- not applicable" % category
        }
        logger.info(
            "\u2717 Category 4 supplementary agent suppressed "
            "-- Category %s", category
        )

    # -- STEP 11: Endpoint Evidence Filter Agent --
    logger.info("STEP 11: Endpoint Evidence Filter Agent")
    logger.info("-" * 40)
    if category in ["1", "2", "3"]:
        current_articles = schema["evidence"]["pubmed_citations"]
        filter_result = filter_evidence_for_endpoints(
            schema["metadata"]["disease_name"],
            current_articles
        )
        schema["evidence"]["pubmed_citations"] = (
            filter_result["retained"])
        schema["audit_trail"][
            "endpoint_evidence_filter_output"] = {
            "retained_count": filter_result["retained_count"],
            "excluded_count": filter_result["excluded_count"],
            "batches_filtered": filter_result[
                "batches_filtered"],
            "batches_fallback": filter_result[
                "batches_fallback"],
            # Calibration fields persisted (v3.12). Previously these
            # two were computed by the filter but dropped at the
            # orchestrator persistence boundary, so the collector
            # could never see them. .get keeps this robust if an
            # older filter build omits one.
            "fallback_rate": filter_result.get("fallback_rate"),
            "articles_retained_unfiltered": filter_result.get(
                "articles_retained_unfiltered"),
            "excluded_pmids": filter_result["excluded_pmids"],
            "agent_version": filter_result["agent_version"],
            "date": filter_result["date"]
        }
        existing_excluded = schema["evidence"].get(
            "pubmed_excluded_pmids", [])
        existing_excluded.extend(
            filter_result["excluded_pmids"])
        schema["evidence"][
            "pubmed_excluded_pmids"] = existing_excluded

        schema["metadata"]["agents_run"].append(
            "endpoint_evidence_filter_agent")
        logger.info(
            "\u2713 Endpoint evidence filter complete -- "
            "%d retained, %d excluded",
            filter_result["retained_count"],
            filter_result["excluded_count"]
        )
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "endpoint_evidence_filter_agent",
            "reason": (
                "Category 4 -- endpoint filter only runs "
                "for Categories 1, 2, 3"
            ),
            "date": str(date.today())
        })
        schema["audit_trail"][
            "endpoint_evidence_filter_output"] = {
            "suppressed": True,
            "reason": "Category 4 -- not applicable"
        }
        logger.info(
            "\u2717 Endpoint evidence filter suppressed "
            "-- Category 4")

    # -- STEP 12: Generative Agent --
    logger.info("STEP 12: Generative Agent")
    logger.info("-" * 40)
    if category in ["1", "2", "3"]:
        (articles_for_generative,
         stripped_count,
         stripped_pmids) = _strip_case_reports(
            schema["evidence"]["pubmed_citations"]
        )
        if stripped_count > 0:
            logger.info(
                "  Stripped %d case report(s)/protocol(s) "
                "before generative agent", stripped_count
            )
            schema["audit_trail"][
                "case_reports_stripped"] = stripped_pmids
            schema["audit_trail"][
                "case_reports_stripped_count"] = (
                stripped_count)

        schema_for_generative = dict(schema)
        schema_for_generative["evidence"] = dict(
            schema["evidence"])
        schema_for_generative["evidence"][
            "pubmed_citations"] = articles_for_generative

        generative_output = generate_endpoint_framework(
            schema_for_generative)

        # Persist generative degradation for the calibration block
        # (v3.12), regardless of success: truncation, an
        # empty-response fallback, malformed endpoint objects, or an
        # endpoint_type the generative step had to coerce are
        # process-health signals on the one generative step.
        # generative_agent v5.1 surfaces all four at the TOP LEVEL of
        # its return (the "generative_agent rewrite" the v3.12 note
        # anticipated), so these top-level reads now land instead of
        # returning None.
        schema["audit_trail"]["generative_calibration"] = {
            "generation_truncated": generative_output.get(
                "generation_truncated"),
            "generated_from_fallback": generative_output.get(
                "generated_from_fallback"),
            "malformed_endpoint_count": generative_output.get(
                "malformed_endpoint_count"),
            "defaulted_endpoint_type_count": generative_output.get(
                "defaulted_endpoint_type_count"),
        }

        if generative_output.get("success"):
            framework = generative_output.get(
                "endpoint_framework", {})
            schema["endpoints"]["generated_framework"] = \
                framework
            schema["metadata"]["agents_run"].append(
                "generative_agent")
            endpoint_count = len(
                framework.get("evidence_based_endpoints", []))
            logger.info(
                "\u2713 Generative agent completed -- "
                "%d endpoint object(s) returned",
                endpoint_count
            )
        else:
            schema["metadata"]["agents_suppressed"].append({
                "agent": "generative_agent",
                "reason": generative_output.get(
                    "error", "Unknown"),
                "date": str(date.today())
            })
            logger.warning("\u2717 Generative agent failed")
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "generative_agent",
            "reason": "Category 4 -- %s" % rationale,
            "date": str(date.today())
        })
        logger.info(
            "\u2717 Generative agent suppressed -- Category 4")

    # -- STEP 13: Endpoint Plausibility Challenge Agent --
    logger.info("STEP 13: Endpoint Plausibility Challenge Agent")
    logger.info("-" * 40)
    plausibility_challenge = challenge_endpoint_plausibility(
        schema)
    schema["audit_trail"]["endpoint_plausibility_output"] = \
        plausibility_challenge
    schema["metadata"]["agents_run"].append(
        "endpoint_plausibility_challenge_agent")
    severity = plausibility_challenge.get("severity")
    if severity == "FAIL":
        schema["audit_trail"]["human_review_required"] = True
        logger.warning(
            "\u2717 Endpoint plausibility FAIL "
            "-- human review required")
    elif severity == "FLAG":
        logger.warning(
            "\u26a0\ufe0f  Endpoint plausibility FLAG -- %s",
            plausibility_challenge.get('recommendation'))
    elif severity == "UNVERIFIED":
        # Infrastructure failure (review could not complete). Set
        # aside for calibration -- not a content verdict and not
        # escalated.
        logger.warning(
            "\u26a0\ufe0f  Endpoint plausibility UNVERIFIED "
            "-- set aside for calibration, not escalated")
    else:
        scope = plausibility_challenge.get(
            "scope_discipline_check", "PASS")
        logger.info(
            "\u2713 Endpoint plausibility PASS -- scope: %s",
            scope)

    # -- STEP 14: Citation Integrity Agent --
    logger.info("STEP 14: Citation Integrity Agent")
    logger.info("-" * 40)
    if category in ["1", "2", "3"]:
        citation_result = verify_citations(schema)
        schema["audit_trail"]["citation_integrity_output"] = \
            citation_result
        if citation_result.get("suppressed"):
            schema["metadata"]["agents_suppressed"].append({
                "agent": "citation_integrity_agent",
                "reason": citation_result.get("reason"),
                "date": str(date.today())
            })
            logger.info(
                "\u2717 Citation integrity suppressed -- %s",
                citation_result.get('reason'))
        else:
            schema["metadata"]["agents_run"].append(
                "citation_integrity_agent")
            score = citation_result.get("integrity_score", 0)
            red = citation_result.get("red_count", 0)
            yellow = citation_result.get("yellow_count", 0)
            pipeline_errors = citation_result.get(
                "pipeline_error_count", 0)
            out_of_set = citation_result.get(
                "out_of_set_count", 0)
            hallucinations = citation_result.get(
                "hallucination_count", 0)
            logger.info(
                "\u2713 Citation integrity -- score: %.0f%%, "
                "green: %d, yellow: %d, red: %d "
                "(hallucinations: %d, pipeline errors: %d, "
                "out of set: %d)",
                score,
                citation_result.get("green_count", 0),
                yellow, red,
                hallucinations, pipeline_errors, out_of_set
            )
            if red > 0:
                # A citation-integrity RED (hallucination /
                # out-of-set / pipeline-error) is healthy system
                # behavior: the bad citation is caught and suppressed,
                # and cannot reach the document (it can never be
                # claim-verified and placed; the suppression-leak gate
                # guarantees this). It is recorded in the audit trail
                # for later calibration analysis, NOT escalated to
                # human review and NOT document-blocking. (The
                # citation_integrity_agent itself no longer sets
                # human_review_required.)
                logger.info(
                    "  %d citation(s) suppressed and recorded for "
                    "calibration (healthy system behavior, not "
                    "escalated)", red)
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "citation_integrity_agent",
            "reason": "Category 4 -- no framework to verify",
            "date": str(date.today())
        })
        logger.info(
            "\u2717 Citation integrity suppressed "
            "-- Category 4")

    # -- STEP 15: Claim Verification Agent --
    logger.info("STEP 15: Claim Verification Agent")
    logger.info("-" * 40)
    if category in ["1", "2", "3"]:
        claim_result = verify_claims(schema)
        schema["audit_trail"]["claim_verification_output"] = \
            claim_result
        if claim_result.get("suppressed"):
            schema["metadata"]["agents_suppressed"].append({
                "agent": "claim_verification_agent",
                "reason": claim_result.get("reason"),
                "date": str(date.today())
            })
            logger.info(
                "\u2717 Claim verification suppressed -- %s",
                claim_result.get('reason'))
        else:
            schema["metadata"]["agents_run"].append(
                "claim_verification_agent")
            verdict = claim_result.get("overall_verdict")
            red_contradiction = claim_result.get(
                "red_contradiction_count", 0)
            red_no_mention = claim_result.get(
                "red_no_mention_count", 0)
            # Calibration readout (claim_verification_agent v4.3).
            # The agent no longer mislabels verification failures
            # and missing abstracts as RED_NO_MENTION; it sets them
            # aside as YELLOW_UNVERIFIED and reports them here. These
            # citations do NOT count toward placement (unverifiable
            # evidence never goes forward) and do NOT escalate to
            # human review -- consistent with the specificity-first
            # bar. They are surfaced because the unverified rate is a
            # fleet-scale calibration signal: a rising rate across a
            # run points at infrastructure or upstream abstract
            # capture, investigable at scale rather than per disease.
            # (Replaces the v3.9 parse_error_count logging; that
            # field no longer exists in v4.3.)
            unverified = claim_result.get("unverified_count", 0)
            unverified_api = claim_result.get(
                "unverified_api_count", 0)
            unverified_no_abstract = claim_result.get(
                "unverified_no_abstract_count", 0)
            unverified_rate = claim_result.get(
                "unverified_rate", 0.0)
            if verdict == "FAIL":
                # A RED_CONTRADICTION is the system catching a claim
                # the abstract contradicts and DROPPING that PMID from
                # the count -- healthy system behavior, not a failure
                # a human resolves. The dropped PMID cannot be placed
                # and cannot reach the document; the suppression-leak
                # gate (Step 17) guarantees that. So a contradiction
                # is suppressed and recorded for calibration, NOT
                # escalated: it does not set human_review_required and
                # does not block the document. (The contradiction
                # count is recorded in the audit trail for later
                # calibration analysis.)
                logger.warning(
                    "\u2717 Claim verification RED_CONTRADICTION "
                    "-- %d citation(s) contradicted by their "
                    "abstract; suppressed and recorded for "
                    "calibration (healthy system behavior, not "
                    "escalated)",
                    red_contradiction)
            elif verdict == "NO_ENDPOINTS_TO_VERIFY":
                # Not a verified pass and not a failure -- the
                # framework carried no named endpoints, so nothing
                # was checked. Logged honestly so "nothing checked"
                # is never read as "verified clean." Does not gate;
                # the document-block gate keys only on FAIL.
                logger.info(
                    "\u2012 Claim verification: NO_ENDPOINTS_TO_"
                    "VERIFY -- framework present but contained no "
                    "named endpoints; nothing was checked")
            else:
                logger.info(
                    "\u2713 Claim verification PASS")
            if red_no_mention > 0:
                logger.info(
                    "  %d PMID(s) dropped from citation "
                    "counts (not mentioned in abstract)",
                    red_no_mention)
            # Surface the unverified (YELLOW) calibration signal.
            # Set aside, not counted, not escalated -- recorded so a
            # high unverified rate is visible per disease and
            # queryable across the fleet.
            if unverified > 0:
                logger.warning(
                    "  \u26a0 CALIBRATION: %d citation(s) set aside "
                    "as UNVERIFIED (%.1f%%) -- %d verification "
                    "failure, %d no-abstract. Not counted toward "
                    "placement and not escalated; recorded for "
                    "fleet-scale calibration.",
                    unverified, unverified_rate * 100,
                    unverified_api, unverified_no_abstract)
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "claim_verification_agent",
            "reason": "Category 4 -- no framework to verify",
            "date": str(date.today())
        })
        logger.info(
            "\u2717 Claim verification suppressed "
            "-- Category 4")

    # -- STEP 16: Endpoint Placement Gate --
    logger.info("STEP 16: Endpoint Placement Gate")
    logger.info("-" * 40)
    if category in ["1", "2", "3"]:
        claim_output = schema["audit_trail"].get(
            "claim_verification_output", {})
        if claim_output.get("suppressed"):
            schema["metadata"]["agents_suppressed"].append({
                "agent": "endpoint_placement_gate",
                "reason": (
                    "Claim verification suppressed -- no "
                    "verified endpoints to place"
                ),
                "date": str(date.today())
            })
            logger.info(
                "\u2717 Placement gate suppressed -- claim "
                "verification produced no result")
        else:
            placement_result = assign_placement(claim_output)
            schema["endpoints"]["placement"] = placement_result
            schema["metadata"]["agents_run"].append(
                "endpoint_placement_gate")
            counts = placement_result.get("counts", {})
            logger.info(
                "\u2713 Placement gate complete -- "
                "%d in 3B, %d excluded",
                counts.get("3B", 0),
                counts.get("excluded", 0)
            )
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "endpoint_placement_gate",
            "reason": "Category 4 -- no framework to place",
            "date": str(date.today())
        })
        logger.info(
            "\u2717 Placement gate suppressed -- Category 4")

    # -- STEP 17: Suppression Leak Gate --
    # The guarantee: a citation the pipeline suppressed must never
    # reach the placed set the document renders. Deterministic, no
    # model call. Runs after placement, before the document. A leak
    # is the one genuine failure -- it means the suppression machinery
    # itself broke, which calls the whole generation process into
    # question, not just this disease. _document_blocked hard-stops
    # the document on a leak. A clean result proceeds silently.
    logger.info("STEP 17: Suppression Leak Gate")
    logger.info("-" * 40)
    leak_result = check_suppression_leak(schema)
    schema["audit_trail"]["suppression_leak_output"] = leak_result
    schema["metadata"]["agents_run"].append("suppression_leak_gate")
    if leak_result.get("leaked"):
        # A suppressed citation reached placement. Escalate: this is
        # a systemic suppression failure, not a per-disease issue.
        schema["audit_trail"]["human_review_required"] = True
        logger.error(
            "\u2717 SUPPRESSION LEAK -- a suppressed citation "
            "reached the placed set. Document will be hard-stopped; "
            "the generation process must be reviewed before the run "
            "is trusted.")
    else:
        logger.info(
            "\u2713 Suppression-leak gate clean -- no suppressed "
            "citation reached placement")

    # -- STEP 18: Comparator + Endpoint Recovery --
    # The comparator compares the prior release against the CURRENT
    # placement (which now exists, after 16) and classifies each
    # prior 3B endpoint absent from the current generation. An
    # endpoint absent for a non-evidence reason -- generative variance,
    # or a supporting PMID merely not retrieved this run while NOT
    # retracted -- is flagged for retention, carrying its FULL prior
    # endpoint object. Those flagged endpoints are routed to the
    # recovery agent, which returns sealed, gate-shaped placement
    # additions, and the orchestrator SPLICES them into the current
    # placement before the document is rendered. The correction is
    # invisible to the document agent and change report (they render
    # the sealed placement and never know recovery happened).
    #
    # Only retraction / expression of concern removes a published
    # endpoint, and the comparator reports that removal with its cause;
    # such an endpoint is NEVER recovered. Recovery restores a sealed
    # prior decision whose evidence was not retracted -- it does not
    # adjudicate, re-search, or fabricate. Generative-variance recovery
    # is the expected, healthy cost of scale, NOT hallucination and NOT
    # a content error; endpoint_recovery_output is recorded for
    # internal calibration in its own category and is never surfaced
    # publicly.
    logger.info("STEP 18: Comparator + Endpoint Recovery")
    logger.info("-" * 40)
    if run_comparator:
        comparator_output = compare_runs(schema)
        schema["audit_trail"][
            "comparator_output"] = comparator_output
        if comparator_output.get("suppressed"):
            schema["metadata"]["agents_suppressed"].append({
                "agent": "comparator_agent",
                "reason": comparator_output.get("reason"),
                "date": str(date.today())
            })
            logger.info(
                "\u2717 Comparator suppressed -- %s",
                comparator_output.get('reason'))
        else:
            schema["metadata"]["agents_run"].append(
                "comparator_agent")
            logger.info(
                "\u2713 Comparator completed -- state: %s",
                comparator_output.get('state'))
            _run_endpoint_recovery(schema, comparator_output)
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "comparator_agent",
            "reason": (
                "Comparator not triggered -- "
                "run with run_comparator=True to activate"
            ),
            "date": str(date.today())
        })
        schema["audit_trail"]["comparator_output"] = {
            "suppressed": True,
            "reason": "Not triggered"
        }
        logger.info(
            "\u2717 Comparator suppressed -- not triggered "
            "(no endpoint recovery without a comparator diff)")

    # -- STEP 19: Evidence Quality Challenge Agent --
    logger.info("STEP 19: Evidence Quality Challenge Agent")
    logger.info("-" * 40)
    if category in ["1", "2", "3"]:
        evidence_quality = challenge_evidence_quality(schema)
        schema["audit_trail"]["evidence_quality_output"] = \
            evidence_quality
        schema["metadata"]["agents_run"].append(
            "evidence_quality_challenge_agent")
        # evidence_quality_challenge_agent v4.0 is purely
        # informational: severity is always "INFO", and the agent
        # never sets human_review_required. The tier distribution is
        # a DISCLOSURE of what the evidence base is, not a pass/fail
        # bar -- gating on it would smuggle back the RCT standard the
        # FDA plausible-mechanism framework rejects for rare disease.
        # The agent returns neither a "FAIL"/"FLAG" severity nor a
        # "suppressed" flag, so the former severity-escalation and
        # suppressed-handling branches here were dead code and are
        # removed. The per-article tier distribution is logged as
        # information only.
        _grade_counts = evidence_quality.get("grade_counts", {}) or {}
        logger.info(
            "\u2713 Evidence quality (informational) -- "
            "tier distribution: %s",
            _grade_counts if _grade_counts else "not applicable")
    else:
        schema["metadata"]["agents_suppressed"].append({
            "agent": "evidence_quality_challenge_agent",
            "reason": "Category 4 -- no framework to evaluate",
            "date": str(date.today())
        })
        logger.info(
            "\u2717 Evidence quality suppressed -- Category 4")

    # -- CALIBRATION BLOCK POPULATION (v3.12) --
    # Purely additive: routes the signals the agents already wrote to
    # the schema into the consolidated calibration block. Reads only;
    # writes only into schema["calibration"]; changes no behavior.
    _populate_calibration_block(schema)

    # -- AUDIT TRAIL FINALIZATION --
    schema["audit_trail"]["evidence_cutoff_date"] = str(
        date.today())
    schema["audit_trail"]["pipeline_version"] = PIPELINE_VERSION
    schema["audit_trail"]["pipeline_run_date"] = str(date.today())
    schema["audit_trail"]["agents_run_count"] = \
        len(schema["metadata"]["agents_run"])
    schema["audit_trail"]["agents_suppressed_count"] = \
        len(schema["metadata"]["agents_suppressed"])

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE: %s", disease_name)
    logger.info("Category: %s", category)
    logger.info("Pipeline version: %s", PIPELINE_VERSION)
    logger.info(
        "Agents run: %d",
        len(schema['metadata']['agents_run']))
    logger.info(
        "Human review required: %s",
        schema['audit_trail'].get(
            'human_review_required', False))
    logger.info("=" * 60)

    return schema


def run_delphi_mode(
        orpha_id: str,
        disease_name: str,
        run_comparator: bool = False) -> dict[str, Any]:
    from delphi_synthesis_agent import synthesize_delphi_runs

    logger.info("=" * 60)
    logger.info("DELPHI MODE: %s", disease_name)
    logger.info("Running 3 independent pipeline passes...")
    logger.info("=" * 60)

    schemas = []
    for i in range(3):
        logger.info("--- Delphi Run %d of 3 ---", i + 1)
        schema = run_pipeline(
            orpha_id, disease_name,
            run_comparator=run_comparator)
        schemas.append(schema)
        if i < 2:
            logger.info(
                "Waiting 60 seconds before next Delphi run...")
            time.sleep(60)

    delphi_result = synthesize_delphi_runs(
        schemas, disease_name)

    safe_name = disease_name.lower().replace(" ", "_")[:50]
    output_filename = (
        "%s_delphi_%s.json" % (safe_name, str(date.today()))
    )
    try:
        with open(output_filename, "w") as f:
            json.dump(delphi_result, f, indent=2)
        logger.info(
            "Delphi JSON saved to: %s", output_filename)
    except OSError as exc:
        logger.error(
            "Failed to write Delphi JSON: %s", exc)

    logger.info(
        "Delphi verdict: %s",
        delphi_result.get('delphi_verdict'))
    logger.info(
        "Minority positions: %d",
        len(delphi_result.get('minority_positions', [])))

    return delphi_result


def _process_one_disease(orpha_id: str,
                         disease_name: str,
                         today: str,
                         checkpoint_file: str,
                         write_checkpoint: Any) -> None:
    """
    Run the full pipeline for one disease and persist its outputs.

    This is the body that used to live inline in the __main__
    batch loop. It is factored out so the loop can wrap it in a
    single try/except: an unhandled exception raised anywhere in
    here is caught by the caller, logged, and the batch continues
    to the next disease instead of crashing. A disease that raises
    is deliberately NOT checkpointed (this function only reaches
    the checkpoint write on a clean run), so it is retried on the
    next run, exactly as a pipeline-error disease is.

    Behavior for a single disease is identical to the previous
    inline body: run pipeline, write JSON, evaluate the document
    block gate, render or suppress the document, then checkpoint
    if there was no pipeline error.
    """
    result = run_pipeline(orpha_id, disease_name)
    safe_name = (
        disease_name.lower().replace(" ", "_")[:50])
    output_filename = "%s_%s.json" % (safe_name, today)
    try:
        with open(output_filename, "w") as f:
            json.dump(result, f, indent=2)
        logger.info("JSON saved to: %s", output_filename)
    except OSError as exc:
        logger.error("Failed to write JSON: %s", exc)

    # -- DOCUMENT GENERATION GATE --
    blocked, block_reason = _document_blocked(result)

    if blocked:
        logger.warning(
            "\u2717 DOCUMENT SUPPRESSED: %s",
            disease_name)
        logger.warning(
            "  Reason: %s", block_reason)
        logger.warning(
            "  JSON audit trail written to: %s",
            output_filename)
        logger.warning(
            "  A document is suppressed only by a suppression leak "
            "(the generation process must be reviewed) or a content "
            "human-review flag from a challenge agent. Caught "
            "hallucination, out-of-set, pipeline-error, and "
            "contradiction citations do NOT suppress the document -- "
            "they are healthy system behavior, suppressed and "
            "recorded in the audit trail.")
    else:
        doc_filename = (
            disease_name.replace(" ", "_")[:50] +
            "_Library_Entry.docx"
        )
        create_library_entry(result, doc_filename)

    if not result.get("audit_trail", {}).get(
            "pipeline_error"):
        write_checkpoint(
            checkpoint_file,
            orpha_id,
            disease_name,
            result["classification"].get(
                "category", "unknown")
        )
        logger.info(
            "Checkpoint written: %s", disease_name)
    else:
        logger.warning(
            "Pipeline error -- %s NOT checkpointed, "
            "will retry on next run",
            disease_name
        )

    # -- SUPPRESSED-AND-RECORDED NOTIFICATION (honest) --
    # Report how many bad citations the system caught and suppressed
    # this disease. These are healthy system behavior, recorded in the
    # run's audit trail for later calibration analysis. This clean
    # orchestrator does NOT run a calibration workflow over them -- the
    # message claims only what is true: the events are recorded in the
    # audit trail. The separate calibration version of the pipeline is
    # what consumes them.
    _audit = result.get("audit_trail", {}) or {}
    _cit = _audit.get("citation_integrity_output", {}) or {}
    _claim = _audit.get("claim_verification_output", {}) or {}
    _hall = _cit.get("hallucination_count", 0) or 0
    _oos = _cit.get("out_of_set_count", 0) or 0
    _perr = _cit.get("pipeline_error_count", 0) or 0
    _contra = _claim.get("red_contradiction_count", 0) or 0
    _suppressed_total = _hall + _oos + _perr + _contra
    if _suppressed_total:
        logger.info(
            "Suppressed and recorded in audit trail for %s: "
            "%d hallucination(s), %d out-of-set, %d pipeline-error, "
            "%d contradiction(s) -- healthy system behavior, recorded "
            "for later calibration analysis (no calibration workflow "
            "runs in this clean orchestrator).",
            disease_name, _hall, _oos, _perr, _contra)

    logger.info(
        "Done: %s -- Category %s\n",
        disease_name,
        result['classification']['category']
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(message)s")

    diseases = [
        ("355", "Gaucher disease"),
        ("487", "Krabbe disease"),
        ("561854", "FOXG1 syndrome"),
        ("500180",
         "Childhood-onset motor and cognitive regression syndrome"),
    ]

    today = str(date.today())

    _CHECKPOINT_FILE = "pipeline_checkpoint.json"

    def _load_checkpoint(path: str) -> set:
        """
        Return the set of ORPHA IDs already completed.

        Absent file -> empty set (a normal first run). A file that is
        present but unreadable, or not the expected list of entries,
        is a hard stop rather than a silent empty set: silently
        treating a corrupt checkpoint as "nothing done" would re-run
        the entire completed batch and spend the tokens again. Entries
        missing an orpha_id are skipped, not fatal.
        """
        if not os.path.exists(path):
            return set()
        try:
            with open(path) as _f:
                data = json.load(_f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(
                "Checkpoint file %s is present but unreadable (%s). "
                "Refusing to continue: proceeding would silently "
                "re-run every completed disease. Inspect or remove "
                "the file, then restart.", path, exc)
            raise SystemExit(1)
        if not isinstance(data, list):
            logger.error(
                "Checkpoint file %s did not contain a list of "
                "entries. Refusing to continue for the same reason. "
                "Inspect or remove the file, then restart.", path)
            raise SystemExit(1)
        completed = {
            entry["orpha_id"] for entry in data
            if isinstance(entry, dict) and "orpha_id" in entry
        }
        logger.info(
            "Checkpoint loaded -- %d disease(s) already "
            "completed, skipping them",
            len(completed)
        )
        return completed

    def _write_checkpoint(path: str,
                          orpha_id: str,
                          disease_name: str,
                          category: str) -> None:
        """
        Append one completed disease to the checkpoint, crash-safely.

        The prior checkpoint is read, the new entry appended in
        memory, and the result written to a temp file that is
        atomically moved into place with os.replace. A process killed
        mid-write leaves either the intact prior checkpoint or the
        complete new one -- never a truncated file. If the existing
        checkpoint is present but unreadable, the write is abandoned
        rather than overwriting it: overwriting would drop every prior
        entry and force a full re-run. That disease is re-checkpointed
        on the next clean write once the file is repaired or removed.
        """
        existing: list = []
        if os.path.exists(path):
            try:
                with open(path) as _f:
                    loaded = json.load(_f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.error(
                    "Checkpoint %s present but unreadable (%s); not "
                    "overwriting so prior progress is preserved. %s "
                    "will be re-checkpointed once the file is repaired "
                    "or removed.", path, exc, disease_name)
                return
            if not isinstance(loaded, list):
                logger.error(
                    "Checkpoint %s is not a list; not overwriting so "
                    "prior progress is preserved. %s re-checkpointed "
                    "later.", path, disease_name)
                return
            existing = loaded
        if any(
            isinstance(e, dict) and e.get("orpha_id") == orpha_id
            for e in existing
        ):
            # Already checkpointed this disease -- do not append a
            # duplicate entry (keeps the checkpoint file free of
            # silent drift). First write wins.
            logger.info(
                "Checkpoint already has %s (ORPHA:%s); not "
                "re-appending.", disease_name, orpha_id)
            return
        existing.append({
            "orpha_id": orpha_id,
            "disease_name": disease_name,
            "category": category,
            "completed_date": str(date.today()),
        })
        tmp_path = "%s.tmp" % path
        try:
            with open(tmp_path, "w") as _f:
                json.dump(existing, _f, indent=2)
                _f.flush()
                os.fsync(_f.fileno())
            os.replace(tmp_path, path)
        except OSError as exc:
            logger.error(
                "Failed to write checkpoint for %s: %s",
                disease_name, exc
            )

    completed_orpha_ids = _load_checkpoint(_CHECKPOINT_FILE)

    failed_diseases: list[dict[str, str]] = []

    for orpha_id, disease_name in diseases:

        if orpha_id in completed_orpha_ids:
            logger.info(
                "SKIP (checkpoint): %s (ORPHA:%s)",
                disease_name, orpha_id
            )
            continue

        try:
            _process_one_disease(
                orpha_id,
                disease_name,
                today,
                _CHECKPOINT_FILE,
                _write_checkpoint,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "\u2717 UNHANDLED EXCEPTION processing %s "
                "(ORPHA:%s): %s -- recording and continuing to "
                "the next disease. This disease was NOT "
                "checkpointed and will be retried on the next "
                "run.",
                disease_name, orpha_id, exc
            )
            failed_diseases.append({
                "orpha_id": orpha_id,
                "disease_name": disease_name,
                "error": str(exc),
            })
            continue

    if failed_diseases:
        logger.warning("=" * 60)
        logger.warning(
            "RUN COMPLETE WITH %d FAILED DISEASE(S) "
            "(not checkpointed; will retry on next run):",
            len(failed_diseases)
        )
        for entry in failed_diseases:
            logger.warning(
                "  \u2717 %s (ORPHA:%s): %s",
                entry["disease_name"],
                entry["orpha_id"],
                entry["error"]
            )
        logger.warning("=" * 60)
    else:
        logger.info(
            "Run complete -- no unhandled disease-level "
            "failures.")
