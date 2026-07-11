"""
config.py
---------
Rare Disease Pre-Competitive Endpoint Library
Independent Women's Center for Better Health
Central configuration – single source of truth for all constants.
All agents import from this module. Change a value here and it
applies everywhere. Do not hardcode thresholds in agent files.
QUARTERLY UPDATE NOTE:
Review thresholds before each quarterly rebuild. Do not change
without documenting the reason in the Architectural Decision Log.
"""
import os

# Load a local .env file if python-dotenv is installed. override=True
# makes .env AUTHORITATIVE: any key defined in .env replaces a value
# already present in the shell environment. This closes the "shadow
# key" failure -- a stale NCBI_API_KEY exported in the shell used to
# win over the correct key in .env (load_dotenv does not override by
# default), and NCBI rejected the bad key with HTTP 400 on the POST.
# With override=True the shell value can no longer shadow .env. A key
# that is NOT defined in .env is left untouched, so a shell-only export
# still works when .env does not set that key. If python-dotenv is not
# installed, the environment is read as-is.
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass
# ---------------------------------------------------------------------------
# Pipeline identity
# ---------------------------------------------------------------------------
PIPELINE_VERSION: str = "3.4"
EMAIL: str = "myohanan@independentwomen.com"
# ---------------------------------------------------------------------------
# Secrets (read from environment / .env – never hardcoded)
# ---------------------------------------------------------------------------
# NCBI (PubMed/Entrez) API key. With a registered key NCBI permits the
# higher request rate that NCBI_SLEEP_SECONDS assumes. Read from the
# environment (see the override=True note above for precedence); keep
# the literal value out of source control. .strip() removes any
# trailing newline or surrounding whitespace, which is a second cause
# of the HTTP 400 -- a key carrying a stray "\n" or "\r" from how the
# .env line was written is malformed on the wire even when its
# characters are otherwise correct.
NCBI_API_KEY: str = os.environ.get("NCBI_API_KEY", "").strip()
# Orphanet (orphacode.org) API key. Read through config so the
# authoritative .env load above runs first -- reading os.getenv
# directly in the agent risked seeing an unloaded environment at
# import time and silently falling back to the "test" key even
# when .env set a real one. .strip() mirrors the NCBI treatment
# (a stray newline in the .env line malforms the key on the
# wire). Empty string when unset; the agent then falls back to
# the "test" placeholder with a one-time warning.
ORPHANET_API_KEY: str = os.environ.get(
    "ORPHANET_API_KEY", "").strip()
# ---------------------------------------------------------------------------
# Shared API endpoints (non-secret) -- one source so agents that
# call the same service cannot drift to different URLs.
# ---------------------------------------------------------------------------
# Orphanet clinical-entity endpoint. Used by orphanet_agent and
# biology_agent; both import it here rather than each hardcoding
# the literal, so there is one way this system reaches Orphanet.
ORPHANET_API_BASE: str = (
    "https://api.orphacode.org/EN/ClinicalEntity/orphacode"
)
# FDA surrogate-endpoint table (live HTML source). Used by
# fda_agent. Centralized here so all external endpoints live in
# one place; the agent keeps its own hardcoded fallback table and
# the version/next-update metadata that must stay paired with it.
FDA_TABLE_URL: str = (
    "https://www.fda.gov/drugs/development-resources/"
    "table-surrogate-endpoints-were-basis-drug-approval-or-licensure"
)
# NCBI E-utilities base. pubmed_agent (efetch + esearch) and
# citation_integrity_agent (efetch) build endpoints by appending
# the tool name (e.g. + "efetch.fcgi"), so the shared service
# lives in one place and the tool suffix stays at each call site
# where it is semantically part of the request.
NCBI_EUTILS_BASE: str = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
)
# ---------------------------------------------------------------------------
# Model settings
# ---------------------------------------------------------------------------
# Primary model – generative agent and all challenge agents.
MODEL: str = "claude-sonnet-4-6"
# Maximum tokens per API call.
MAX_TOKENS: int = 16000
# Sampling temperature for all live model calls. 0.0 to minimize
# variance throughout, including the generative derivation step.
# Sonnet 4.6 accepts a custom temperature; Opus 4.8 would reject a
# non-default value with a 400. Claim is "low-temperature /
# variance-minimized," never "deterministic."
TEMPERATURE: float = 0.0
# ---------------------------------------------------------------------------
# Retry and network settings
# ---------------------------------------------------------------------------
# Maximum retry attempts for external API calls before escalating.
MAX_RETRIES: int = 3
# Seconds between NCBI (PubMed/Entrez) API calls, WITH a
# registered API key. NCBI permits 10 req/sec with a key.
NCBI_SLEEP_SECONDS: float = 0.15
# Seconds between NCBI calls WITHOUT a registered key. NCBI
# permits 3 req/sec unauthenticated, so 0.34s is the floor
# (1/3 s rounded up). The PubMed agent selects this value when
# NCBI_API_KEY is empty; keeping both here means neither rate is
# hardcoded in the agent.
NCBI_SLEEP_SECONDS_NO_KEY: float = 0.34
# Seconds between ClinicalTrials.gov API calls.
CLINICALTRIALS_SLEEP_SECONDS: float = 0.5
# ClinicalTrials.gov API page size for trial retrieval queries.
CLINICALTRIALS_PAGE_SIZE: int = 1000
# ---------------------------------------------------------------------------
# Evidence thresholds – LOCKED, see Non-Negotiable Principles
# ---------------------------------------------------------------------------
# Minimum independent PubMed citations for CONFIRMED endpoint (Section 3B).
# Tied to insurance coverage defensibility standards.
# DO NOT lower without documenting reason in Architectural Decision Log.
MIN_PUBMED_CITATIONS: int = 2
# Minimum independent PubMed citations for Category 2 assignment.
MIN_CITATIONS_CATEGORY2: int = 1
# ---------------------------------------------------------------------------
# Maximum acceptable human review flag rate across a full library run.
# Above this rate treat as an architectural problem, not per-disease noise.
MAX_ESCALATION_RATE_PCT: float = 1.0
# ---------------------------------------------------------------------------
# Deterministic matching parameters
# ---------------------------------------------------------------------------
# Maximum length (characters) at which a search term must match on a
# whole-word boundary rather than as a bare substring. Used by
# fda_match_util.term_matches, shared by fda_agent and
# fda_approval_agent. The boundary guard stops a 2-4 character
# abbreviation (e.g. "AR") from substring-matching an unrelated record
# ("arginase 1 deficiency"), which in fda_agent would become a false
# Category 1 -- a fabricated FDA-validated surrogate. Lives here so the
# matching rule has one definition and no agent hardcodes it.
SHORT_TERM_MAX_LEN: int = 4
# ---------------------------------------------------------------------------
# Pipeline batch sizes
# ---------------------------------------------------------------------------
# PubMed articles per Layer 3A Claude relevance filter call.
LAYER3A_BATCH_SIZE: int = 50
# NCBI efetch records per fetch request (pubmed_agent and
# category4_pubmed_agent). Shared so the two NCBI-fetching agents
# use one batch size.
NCBI_FETCH_BATCH_SIZE: int = 200
# NCBI esearch results per page (retmax). Distinct from the fetch
# batch above -- esearch retmax and efetch batching are separate
# NCBI limits, kept as separate dials even though both are 200.
NCBI_SEARCH_PAGE_SIZE: int = 200
# ---------------------------------------------------------------------------
# Calibration reporting thresholds – REPORTING ONLY, NOT GATES
# ---------------------------------------------------------------------------
# These thresholds govern the fleet CALIBRATION COLLECTOR's readout and
# NOTHING ELSE. They are distinct in kind from MAX_ESCALATION_RATE_PCT
# above: that constant is an escalation-rate ceiling the architect reads
# as an architectural-problem signal; these are the normal-range markers
# the collector renders BESIDE each monitored fleet rate so a human
# reading the quarterly readout can see at a glance whether a rate sits
# inside or outside its expected band.
#
# CRITICAL -- these do not gate, suppress, halt, or change any category
# or document. The collector is an audit instrument: it reports rates
# with their denominators and the contributing disease IDs, and marks
# each rate against the threshold below so the number is LEGIBLE. The
# human decides what to do. A rate above its threshold is shown as
# over-band; it is never acted on by the machinery. Crossing a threshold
# is information, not an instruction.
#
# A monitored rate is a GAUGE. The content-error tier is different in
# kind -- it is an ALARM, not a gauge, and its threshold is conceptually
# zero: ANY hallucination, out-of-set citation, contradiction, or
# pipeline error is surfaced as an emergency with the specific disease
# IDs and PMIDs named, never folded into a rate. CONTENT_ERROR_THRESHOLD
# is recorded as 0 to make that explicit and self-documenting in the
# readout; it is an alarm floor, not a tolerance band.
#
# Values are initial calibration-period estimates. The whole point of the
# collector is to learn what "normal" actually is across a full library
# run; expect to revisit these once real fleet distributions are visible.
# Change only with an Architectural Decision Log entry.

# Alarm floor for the content-error tier. Conceptually zero: any content
# error is an emergency, named and itemized, never rendered as a rate.
CONTENT_ERROR_THRESHOLD: float = 0.0

# Gauge bands for monitored technical-failure rates, expressed as
# fractions (0.05 == 5%). A rate at or above its band is rendered
# over-band in the readout. Keyed by the collector's rate names so the
# collector can look up each threshold by the rate it is reporting.
CALIBRATION_THRESHOLDS: dict[str, float] = {
    # --- by source ---
    "pubmed_fetch_failure_rate": 0.05,
    "pubmed_not_returned_rate": 0.05,
    "pubmed_no_abstract_rate": 0.10,
    "pubmed_id_retrieval_shortfall_rate": 0.05,
    "pubmed_layer3_fallback_rate": 0.10,
    "orphadata_epidemiology_unavailable_rate": 0.50,
    "orphadata_natural_history_unavailable_rate": 0.50,
    "fda_table_non_live_rate": 0.05,
    # Drug-approval database load failure. The file is SHARED, so a
    # single broken file flags every disease -- a high rate means
    # the shared orphan-drug file failed to load for the run, not a
    # per-disease condition.
    "fda_approval_load_failure_rate": 0.05,
    # --- by model call (unverified = review could not complete) ---
    "claim_verification_unverified_rate": 0.10,
    "citation_integrity_unverified_rate": 0.10,
    "endpoint_plausibility_unverified_rate": 0.10,
    "endpoint_evidence_filter_fallback_rate": 0.10,
    "generative_degradation_rate": 0.05,
    "category4_supplementary_retrieval_failed_rate": 0.20,
    # --- structural / miscategorization (incidence rates) ---
    "no_endpoints_to_verify_rate": 0.10,
    "no_framework_citations_rate": 0.05,
    "challenge_zero_articles_rate": 0.02,
    "gene_resolution_file_load_degraded_rate": 0.01,
    # --- delphi (within-run generative stability) ---
    # The one Delphi number that behaves like a calibration gauge: the
    # fraction of Delphi-mode diseases whose three runs DIVERGED on
    # placement DESPITE identical retrieval inputs. High input variance
    # absorbed into output consensus is healthy (the gates worked); a
    # divergence on STABLE input means the scaffolding held but the
    # model wobbled -- a "tighten determinism" signal. This rate earns
    # a band; the rest of the Delphi readout (verdict distribution,
    # minority positions) is reported without bands. Tight by design:
    # stable-input divergence should be rare.
    "delphi_diverged_despite_stable_input_rate": 0.05,
}
