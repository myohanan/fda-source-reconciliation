"""
disease_resolution_agent.py
---------------------------
Rare Disease Pre-Competitive Endpoint Library
Independent Women's Center for Better Health

Disease Resolution Layer for the Rare Disease Pre-Competitive
Endpoint Library.

Resolves a disease identity into a canonical object BEFORE gene
lookup, so that gene resolution is not asked to also solve disease
identity, synonym, and hierarchy problems. The canonical object is
consumed directly by all downstream agents.

resolve_disease runs five sequential steps:
  Step 1 -- Disease identity: resolve the preferred name, synonyms,
            and Orphanet disorder_type from the nomenclature.
  Step 2 -- Hierarchy: resolve parent and child ORPHA IDs.
  Step 3 -- MONDO ID: map the ORPHA ID to its MONDO identifier.
  Step 4 -- Disease class: classify from Orphanet's own
            disorder_type field via DISORDER_TYPE_TO_CLASS
            (MONOGENIC, HETEROGENEOUS, SYNDROMIC, PHENOCOPY,
            PATHWAY_DISORDER, PREDISPOSITION, UNKNOWN). A
            disorder_type of "Disease" is resolved to MONOGENIC or
            HETEROGENEOUS by inspecting whether child diseases share
            genes.
  Step 5 -- Gene resolution: the disease class selects a lookup
            strategy via CLASS_TO_STRATEGY (SINGLE_GENE for
            monogenic/predisposition, GENE_FAMILY for
            heterogeneous/pathway, etc.), then genes are drawn from
            orphadata, the OMIM chain, or gene-family expansion as
            the strategy dictates. Gene confidence is set from
            ClinGen classification, with an eponymous-gene upgrade
            when the gene symbol appears as a whole word in the
            disease name.

Classification is data-driven off Orphanet's disorder_type field
rather than per-disease exception rules, so a newly typed disease
resolves without new code as long as Orphanet has typed it.

resolution_status records the outcome: RESOLVED / HIGH_CONFIDENCE /
MODERATE_CONFIDENCE when a usable result was produced,
CONFLICT_DETECTED when multiple causative genes were found, and
HUMAN_REVIEW_REQUIRED when the disease identity was not found in the
nomenclature or no gene could be resolved for a class that expects
one. This status is set at resolution time, before category
assignment; how it is consumed is a downstream concern.
Source-file load health is recorded per run
(file_load_degraded / degraded_files): a missing or unreadable
shared source file is surfaced as a calibration signal rather than
silently depressing gene confidence across the run.
"""

import csv
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)

AGENT_VERSION: str = "2.7"

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

NOMENCLATURE_FILE: str = os.path.join(
    _BASE_DIR, "ORPHAnomenclature_en_2025.xml")
PARENT_MAP_FILE: str = os.path.join(
    _BASE_DIR, "orphadata_gene_parent_map.json")
MONDO_FILE: str = os.path.join(_BASE_DIR, "orpha_to_mondo.json")
GENES_FILE: str = os.path.join(_BASE_DIR, "orphadatagenes.xml")
PRODUCT1_FILE: str = os.path.join(_BASE_DIR, "orphadata_product1.xml")
MIM2GENE_FILE: str = os.path.join(_BASE_DIR, "mim2gene_medgen.txt")
HGNC_FILE: str = os.path.join(_BASE_DIR, "hgnc_complete_set.txt")
CLINGEN_FILE: str = os.path.join(_BASE_DIR, "clingen_gene_disease.csv")

DISORDER_TYPE_TO_CLASS = {
    "Disease": "MONOGENIC_OR_HETEROGENEOUS",
    "Etiological subtype": "PHENOCOPY",
    "Clinical subtype": "PHENOCOPY",
    "Histopathological subtype": "PHENOCOPY",
    "Morphological anomaly": "PHENOCOPY",
    "Malformation syndrome": "SYNDROMIC",
    "Clinical syndrome": "SYNDROMIC",
    "Clinical group": "HETEROGENEOUS",
    "Category": "HETEROGENEOUS",
    "Biological anomaly": "PATHWAY_DISORDER",
    "Particular clinical situation in a disease or syndrome": "UNKNOWN",
}

SUBTYPE_DISORDER_TYPES = {
    "Etiological subtype",
    "Clinical subtype",
    "Histopathological subtype",
    "Morphological anomaly",
}

CLASS_TO_STRATEGY = {
    "MONOGENIC": "SINGLE_GENE",
    "HETEROGENEOUS": "GENE_FAMILY",
    "SYNDROMIC": "SYNDROMIC_MANIFESTATION",
    "PHENOCOPY": "PHENOCOPY_EXCLUDED",
    "PREDISPOSITION": "SINGLE_GENE",
    "PATHWAY_DISORDER": "GENE_FAMILY",
    "UNKNOWN": "UNKNOWN",
}

CAUSATIVE_TYPES = {
    "Disease-causing germline mutation(s) in",
    "Disease-causing germline mutation(s) (loss of function) in",
}

# Per-run source-file load health. Keyed by a stable logical file
# name; value is "ok" (file present and parsed -- even if genuinely
# empty), "absent" (file missing), or "error" (file present but the
# read/parse raised). Populated lazily by the loaders on their first
# real load and read by resolve_disease. A key absent from this map
# means that file was never exercised on this run, which is NOT a
# degradation -- we do not claim a file failed when we never tried to
# load it. This is a per-run-environment signal: the source files are
# shared across every disease in a run, so a missing file produces an
# identical flag on all of them.
_FILE_LOAD_HEALTH: Optional[dict[str, str]] = None


def _record_file_health(key: str, status: str) -> None:
    """Record a loader's load outcome for the per-run health map."""
    global _FILE_LOAD_HEALTH
    if _FILE_LOAD_HEALTH is None:
        _FILE_LOAD_HEALTH = {}
    # First-write-wins: a file's verdict is recorded once per run and
    # not overwritten. The memoized loaders write once anyway; the one
    # non-memoized loader (_load_nomenclature) runs per disease, so
    # without this guard a file whose state changed mid-run could
    # retroactively flip the recorded verdict for the whole run --
    # including diseases already resolved cleanly. Recording on first
    # contact keeps the per-run-environment signal stable across the
    # batch, which is the documented intent.
    if key not in _FILE_LOAD_HEALTH:
        _FILE_LOAD_HEALTH[key] = status


def reset_file_load_health() -> None:
    """
    Clear the per-run file-load health map.

    Provided for tests and for any caller that wants a clean per-run
    reading. Not called by the pipeline in normal operation -- the
    map is populated once on first load and is intended to persist
    across a batch run (the files are shared, so the verdict is
    stable).
    """
    global _FILE_LOAD_HEALTH
    _FILE_LOAD_HEALTH = None


def get_file_load_health() -> dict[str, str]:
    """Return a copy of the current per-run file-load health map."""
    return dict(_FILE_LOAD_HEALTH) if _FILE_LOAD_HEALTH else {}


_parent_map: Optional[dict[str, list[str]]] = None
_reverse_map: Optional[dict[str, list[str]]] = None
_mondo_map: Optional[dict[str, str]] = None
_orpha_to_omim: Optional[dict[str, list[str]]] = None
_mim2gene: Optional[dict[str, str]] = None
_hgnc_symbols: Optional[set[str]] = None
_geneid_to_symbol: Optional[dict[str, str]] = None
_clingen: Optional[dict[tuple[str, str], str]] = None
_genes_by_orpha: Optional[dict[str, list[dict[str, str]]]] = None


def _load_parent_map() -> dict[str, list[str]]:
    global _parent_map
    if _parent_map is not None:
        return _parent_map
    if not os.path.exists(PARENT_MAP_FILE):
        _record_file_health("parent_map", "absent")
        _parent_map = {}
        return _parent_map
    try:
        with open(PARENT_MAP_FILE) as f:
            _parent_map = json.load(f)
        _record_file_health("parent_map", "ok")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Parent map load error: %s", exc)
        _record_file_health("parent_map", "error")
        _parent_map = {}
    return _parent_map


def _load_reverse_map() -> dict[str, list[str]]:
    global _reverse_map
    if _reverse_map is not None:
        return _reverse_map
    parent_map = _load_parent_map()
    reverse: dict[str, list[str]] = {}
    for child, parents in parent_map.items():
        for parent in parents:
            if parent not in reverse:
                reverse[parent] = []
            reverse[parent].append(child)
    _reverse_map = reverse
    return _reverse_map


def _load_mondo_map() -> dict[str, str]:
    """
    Load ORPHA-to-MONDO mapping.

    Handles both the legacy flat format {orpha_id: mondo_id} and the
    current format {"_metadata": {...}, "mappings": {orpha_id: mondo_id}}
    produced by build_mondo_lookup.py.
    """
    global _mondo_map
    if _mondo_map is not None:
        return _mondo_map
    if not os.path.exists(MONDO_FILE):
        _record_file_health("mondo", "absent")
        _mondo_map = {}
        return _mondo_map
    try:
        with open(MONDO_FILE) as f:
            raw = json.load(f)
        if "mappings" in raw:
            _mondo_map = raw["mappings"]
        else:
            _mondo_map = raw
        _record_file_health("mondo", "ok")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("MONDO map load error: %s", exc)
        _record_file_health("mondo", "error")
        _mondo_map = {}
    return _mondo_map


def _load_orpha_to_omim() -> dict[str, list[str]]:
    global _orpha_to_omim
    if _orpha_to_omim is not None:
        return _orpha_to_omim
    if not os.path.exists(PRODUCT1_FILE):
        _record_file_health("product1_omim", "absent")
        _orpha_to_omim = {}
        return _orpha_to_omim
    orpha_to_omim: dict[str, list[str]] = {}
    try:
        context = ET.iterparse(PRODUCT1_FILE, events=("end",))
        for _, elem in context:
            if elem.tag == "Disorder":
                code = elem.findtext("OrphaCode")
                if code:
                    omim_ids = []
                    for ref in elem.iter("ExternalReference"):
                        source = ref.findtext("Source")
                        reference = ref.findtext("Reference")
                        if source == "OMIM" and reference:
                            omim_ids.append(reference)
                    if omim_ids:
                        orpha_to_omim[code] = omim_ids
                elem.clear()
        _record_file_health("product1_omim", "ok")
    except (ET.ParseError, OSError) as exc:
        logger.warning("ORPHA-OMIM load error: %s", exc)
        _record_file_health("product1_omim", "error")
    _orpha_to_omim = orpha_to_omim
    return _orpha_to_omim


def _load_mim2gene() -> dict[str, str]:
    global _mim2gene
    if _mim2gene is not None:
        return _mim2gene
    if not os.path.exists(MIM2GENE_FILE):
        _record_file_health("mim2gene", "absent")
        _mim2gene = {}
        return _mim2gene
    mim2gene: dict[str, str] = {}
    try:
        with open(MIM2GENE_FILE) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                cols = line.strip().split("\t")
                if len(cols) >= 2 and cols[1] and cols[1] != "-":
                    mim2gene[cols[0]] = cols[1]
        _record_file_health("mim2gene", "ok")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("mim2gene load error: %s", exc)
        _record_file_health("mim2gene", "error")
    _mim2gene = mim2gene
    return _mim2gene


def _load_hgnc() -> tuple[set[str], dict[str, str]]:
    global _hgnc_symbols, _geneid_to_symbol
    if _hgnc_symbols is not None:
        return _hgnc_symbols, _geneid_to_symbol
    if not os.path.exists(HGNC_FILE):
        _record_file_health("hgnc", "absent")
        _hgnc_symbols = set()
        _geneid_to_symbol = {}
        return _hgnc_symbols, _geneid_to_symbol
    symbols: set[str] = set()
    geneid_to_symbol: dict[str, str] = {}
    try:
        with open(HGNC_FILE) as f:
            header = f.readline().strip().split("\t")
            sym_idx = header.index("symbol")
            eid_idx = (
                header.index("entrez_id")
                if "entrez_id" in header else -1
            )
            for line in f:
                cols = line.strip().split("\t")
                if len(cols) <= sym_idx:
                    continue
                symbol = cols[sym_idx]
                if symbol:
                    symbols.add(symbol)
                if (eid_idx >= 0 and len(cols) > eid_idx
                        and cols[eid_idx]):
                    geneid_to_symbol[cols[eid_idx]] = symbol
        _record_file_health("hgnc", "ok")
    except (OSError, ValueError, IndexError) as exc:
        # ValueError covers a missing/renamed "symbol" column
        # (header.index) and a corrupt-encoding UnicodeDecodeError (a
        # ValueError subclass); IndexError covers a malformed row.
        # Recording "error" degrades the run rather than crashing the
        # disease and leaving HGNC unmarked -- HGNC gates gene-symbol
        # validation, so an un-recorded failure here silently fails
        # every gene's validation across the whole run.
        logger.warning("HGNC load error: %s", exc)
        _record_file_health("hgnc", "error")
    _hgnc_symbols = symbols
    _geneid_to_symbol = geneid_to_symbol
    return _hgnc_symbols, _geneid_to_symbol


def _load_clingen() -> dict[tuple[str, str], str]:
    global _clingen
    if _clingen is not None:
        return _clingen
    if not os.path.exists(CLINGEN_FILE):
        _record_file_health("clingen", "absent")
        _clingen = {}
        return _clingen
    clingen: dict[tuple[str, str], str] = {}
    priority = {
        "Definitive": 4, "Strong": 3, "Moderate": 2, "Limited": 1}
    try:
        with open(CLINGEN_FILE) as f:
            reader = csv.reader(f)
            header_found = False
            gene_idx = class_idx = mondo_idx = None
            for row in reader:
                if not row:
                    continue
                clean = [c.strip().strip('"') for c in row]
                if clean[0] == "GENE SYMBOL":
                    header_found = True
                    try:
                        gene_idx = clean.index("GENE SYMBOL")
                        class_idx = clean.index("CLASSIFICATION")
                        mondo_idx = (
                            clean.index("DISEASE ID (MONDO)")
                            if "DISEASE ID (MONDO)" in clean
                            else None
                        )
                    except ValueError:
                        continue
                    continue
                if (not header_found or gene_idx is None
                        or class_idx is None):
                    continue
                if len(row) <= max(gene_idx, class_idx):
                    continue
                gene = row[gene_idx].strip().strip('"')
                classification = row[class_idx].strip().strip('"')
                if not gene or classification not in priority:
                    continue
                if mondo_idx is not None and len(row) > mondo_idx:
                    mondo_id = row[mondo_idx].strip().strip('"')
                    if mondo_id.startswith("MONDO:"):
                        existing = clingen.get((mondo_id, gene), "")
                        if (priority.get(classification, 0)
                                > priority.get(existing, 0)):
                            clingen[(mondo_id, gene)] = classification
        # Record "ok" only if the header row AND its required columns
        # actually resolved. A file whose "GENE SYMBOL" header never
        # matched (format drift), or matched but whose CLASSIFICATION /
        # GENE SYMBOL columns failed to resolve, reads no data rows and
        # returns an empty map with no exception -- a present-but-
        # unparseable load that would otherwise record "ok" and
        # silently downgrade every gene toward Category 4 with no
        # degraded flag. That case records "error" instead. A header
        # that resolves but yields zero in-priority rows stays "ok":
        # a legitimately empty parse is not a load failure.
        header_parsed = (
            header_found and gene_idx is not None
            and class_idx is not None)
        if header_parsed:
            _record_file_health("clingen", "ok")
        else:
            logger.warning(
                "ClinGen header/columns not resolved -- file format "
                "may have drifted; recording degraded")
            _record_file_health("clingen", "error")
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        logger.warning("ClinGen load error: %s", exc)
        _record_file_health("clingen", "error")
    _clingen = clingen
    return _clingen


def _load_genes_by_orpha() -> dict[str, list[dict[str, str]]]:
    global _genes_by_orpha
    if _genes_by_orpha is not None:
        return _genes_by_orpha
    if not os.path.exists(GENES_FILE):
        _record_file_health("genes", "absent")
        _genes_by_orpha = {}
        return _genes_by_orpha
    genes_by_orpha: dict[str, list[dict[str, str]]] = {}
    try:
        context = ET.iterparse(GENES_FILE, events=("end",))
        for _, elem in context:
            if elem.tag == "Disorder":
                code = elem.findtext("OrphaCode")
                if code:
                    genes = []
                    for assoc in elem.findall(
                            ".//DisorderGeneAssociation"):
                        symbol = assoc.find(".//Gene/Symbol")
                        assoc_type = assoc.find(
                            ".//DisorderGeneAssociationType/Name")
                        if symbol is not None and symbol.text:
                            genes.append({
                                "symbol": symbol.text.strip(),
                                "assoc_type": (
                                    assoc_type.text
                                    if assoc_type is not None
                                    else "Unknown"
                                ),
                            })
                    if genes:
                        genes_by_orpha[code] = genes
                elem.clear()
        _record_file_health("genes", "ok")
    except (ET.ParseError, OSError) as exc:
        logger.warning("genes load error: %s", exc)
        _record_file_health("genes", "error")
    _genes_by_orpha = genes_by_orpha
    return _genes_by_orpha


def _omim_chain(orpha_id: str) -> Optional[str]:
    orpha_to_omim = _load_orpha_to_omim()
    mim2gene = _load_mim2gene()
    hgnc_symbols, geneid_to_symbol = _load_hgnc()
    omim_ids = orpha_to_omim.get(orpha_id, [])
    for omim_id in omim_ids:
        gene_id = mim2gene.get(omim_id)
        if not gene_id:
            continue
        symbol = geneid_to_symbol.get(gene_id)
        if symbol and symbol in hgnc_symbols:
            return symbol
    return None


def _clingen_confidence(gene: str, mondo_id: Optional[str]) -> str:
    if not mondo_id:
        return "Not in ClinGen"
    clingen = _load_clingen()
    mondo_clean = (
        mondo_id if mondo_id.startswith("MONDO:")
        else "MONDO:" + mondo_id
    )
    return clingen.get((mondo_clean, gene), "Not in ClinGen")


def _gene_set_confidence(
        gene_list: list[str], mondo_id: Optional[str]) -> str:
    if not gene_list:
        return "NONE"
    clingen_classes = [
        _clingen_confidence(g, mondo_id) for g in gene_list]
    if "Definitive" in clingen_classes:
        return "CONFIRMED"
    if any(c in ["Strong", "Moderate"] for c in clingen_classes):
        return "HIGH"
    return "LOW"


def _is_eponymous_gene(gene_symbol: str, disease_name: str) -> bool:
    """
    Return True if the gene symbol appears as a whole word in the
    disease name.

    These diseases are definitionally caused by the named gene.
    Examples: FOXG1 syndrome, MECP2 duplication syndrome,
    WDR45-related disorder. Confidence for eponymous genes is
    upgraded to CONFIRMED regardless of ClinGen MONDO ID
    availability.

    The match is word-boundary anchored, not a bare substring test:
    a bare substring test would upgrade a gene whose symbol happens
    to fall inside an unrelated word (a short symbol like "AR"
    matching the "ar" in "Marfan"), driving a wrong LOW -> CONFIRMED
    upgrade. Requiring the symbol to stand as its own token removes
    that false positive while still matching every genuine eponymous
    form, which by naming convention sets the gene off as a token.
    """
    if not gene_symbol or not disease_name:
        return False
    pattern = r"\b" + re.escape(gene_symbol) + r"\b"
    return re.search(
        pattern, disease_name, re.IGNORECASE) is not None


def _get_genes_for_orpha(
        orpha_id: str, causative_only: bool = False) -> list[str]:
    """Return gene symbols for an ORPHA ID, optionally causative only."""
    genes_by_orpha = _load_genes_by_orpha()
    hgnc_symbols, _ = _load_hgnc()
    gene_data = genes_by_orpha.get(orpha_id, [])
    result: list[str] = []
    for gd in gene_data:
        symbol = gd["symbol"]
        assoc_type = gd["assoc_type"]
        if hgnc_symbols and symbol not in hgnc_symbols:
            continue
        if causative_only and assoc_type not in CAUSATIVE_TYPES:
            continue
        if symbol not in result:
            result.append(symbol)
    return result


def _get_gene_family(orpha_id: str) -> list[str]:
    """Return all causative genes across this disease and its children."""
    reverse_map = _load_reverse_map()
    children = reverse_map.get(orpha_id, [])
    gene_set: set[str] = set()
    direct = _get_genes_for_orpha(orpha_id, causative_only=True)
    gene_set.update(direct)
    for child_id in children:
        child_genes = _get_genes_for_orpha(
            child_id, causative_only=True)
        gene_set.update(child_genes)
    return sorted(list(gene_set))


def _children_have_diverse_genes(
        orpha_id: str, child_ids: list[str]) -> bool:
    """Return True if children carry more than 3 distinct genes."""
    if not child_ids:
        return False
    all_child_genes: set[str] = set()
    children_with_genes = 0
    for child_id in child_ids:
        child_genes = set(
            _get_genes_for_orpha(child_id, causative_only=True))
        if child_genes:
            children_with_genes += 1
            all_child_genes.update(child_genes)
    if children_with_genes == 0:
        return False
    return len(all_child_genes) > 3


def _load_nomenclature(orpha_id: str) -> dict[str, Any]:
    """Load disease name, synonyms, and disorder type from Orphanet."""
    result: dict[str, Any] = {
        "found": False,
        "preferred_name": None,
        "synonyms": [],
        "disorder_type": None,
        "classification_level": None,
    }
    if not os.path.exists(NOMENCLATURE_FILE):
        # Missing shared file: record absent for the per-run signal.
        # Affects every disease identically (none can resolve identity
        # from nomenclature), which is exactly the environmental
        # degradation the file-load signal exists to surface.
        _record_file_health("nomenclature", "absent")
        return result
    target_id = str(orpha_id).lstrip("ORPHA:")
    try:
        context = ET.iterparse(
            NOMENCLATURE_FILE, events=("start", "end"))
        inside_target = False
        for event, elem in context:
            if event == "start" and elem.tag == "Disorder":
                inside_target = False
            elif event == "end" and elem.tag == "OrphaCode":
                if elem.text == target_id:
                    inside_target = True
            elif inside_target and event == "end":
                if (elem.tag == "Name"
                        and result["preferred_name"] is None):
                    result["preferred_name"] = elem.text
                    result["found"] = True
                elif elem.tag == "Synonym":
                    if elem.text:
                        result["synonyms"].append(elem.text)
                elif elem.tag == "DisorderType":
                    name_el = elem.find("Name")
                    if name_el is not None:
                        result["disorder_type"] = name_el.text
                elif elem.tag == "ClassificationLevel":
                    name_el = elem.find("Name")
                    if name_el is not None:
                        result["classification_level"] = name_el.text
                elif elem.tag == "Disorder" and result["found"]:
                    elem.clear()
                    break
            if event == "end" and not inside_target:
                elem.clear()
        # A successful parse -- the file loaded and was iterated.
        # "found" False here means this ORPHA id was not in the file,
        # which is a per-disease lookup miss, NOT a file-load failure;
        # the file itself loaded fine, so health is "ok".
        _record_file_health("nomenclature", "ok")
    except (ET.ParseError, OSError) as exc:
        result["parse_error"] = str(exc)
        _record_file_health("nomenclature", "error")
    return result


def resolve_disease(orpha_id: str,
                    disease_name: str) -> dict[str, Any]:
    """
    Main entry point. Produces a Fully Resolved Disease Object.

    All downstream agents consume this object directly.

    On the role of the gene in this library: the gene is
    INFORMATIONAL, not load-bearing. Endpoints are derived from
    the disease's literature, never from the gene; the gene is
    displayed as context and widens PubMed retrieval as an
    additive search term. Because the gene determines nothing
    downstream, gene inclusion is deliberately BROAD: a listed
    gene may be causal (genotypic), or involved in phenotypic
    expression or disease severity, or some combination. Rare-
    disease genetics rarely resolves to a clean one-gene-one-
    disease mapping, and a gene relevant to phenotypic expression
    is a legitimate endpoint-adjacent signal. Over-inclusion
    carries no determinative risk here (it cannot create or
    validate an endpoint); missing a relevant gene would only
    narrow retrieval. Sensitivity is therefore preferred over
    specificity for gene inclusion.

    Args:
        orpha_id: Orphanet disease identifier (numeric or ORPHA:nnn).
        disease_name: Orphanet preferred disease name.

    Returns:
        Canonical disease object dict with gene, class, and confidence.
    """
    logger.info(
        "\nDisease Resolution Agent v%s: %s (ORPHA:%s)",
        AGENT_VERSION, disease_name, orpha_id,
    )
    logger.info("-" * 50)

    notes: list[str] = []
    orpha_id_clean = str(orpha_id).lstrip("ORPHA:")

    logger.info("  Step 1: Disease identity...")
    nom = _load_nomenclature(orpha_id_clean)
    if nom["found"]:
        preferred_name = nom["preferred_name"]
        synonyms = nom["synonyms"]
        disorder_type = nom["disorder_type"]
        is_subtype = disorder_type in SUBTYPE_DISORDER_TYPES
        logger.info(
            "  Found: %s (%s)", preferred_name, disorder_type)
    else:
        preferred_name = disease_name
        synonyms = []
        disorder_type = None
        is_subtype = False
        notes.append("ORPHA:%s not in nomenclature" % orpha_id_clean)

    logger.info("  Step 2: Hierarchy...")
    parent_map = _load_parent_map()
    parent_ids = parent_map.get(orpha_id_clean, [])
    reverse_map = _load_reverse_map()
    child_ids = reverse_map.get(orpha_id_clean, [])
    logger.info(
        "  Parents: %d | Children: %d",
        len(parent_ids), len(child_ids))

    logger.info("  Step 3: MONDO ID...")
    mondo_map = _load_mondo_map()
    mondo_raw = mondo_map.get(orpha_id_clean)
    mondo_id = (
        "MONDO:" + mondo_raw
        if mondo_raw and not mondo_raw.startswith("MONDO:")
        else mondo_raw
    )
    logger.info("  MONDO: %s", mondo_id or "not found")

    logger.info("  Step 4: Disease class...")

    if not disorder_type:
        disease_class = "UNKNOWN"
        notes.append("DisorderType not found -- UNKNOWN")
    else:
        preliminary = DISORDER_TYPE_TO_CLASS.get(
            disorder_type, "UNKNOWN")

        if preliminary == "MONOGENIC_OR_HETEROGENEOUS":
            if child_ids and _children_have_diverse_genes(
                    orpha_id_clean, child_ids):
                disease_class = "HETEROGENEOUS"
                notes.append(
                    "DisorderType 'Disease' with diverse child genes"
                    " -> HETEROGENEOUS")
            else:
                disease_class = "MONOGENIC"
                if child_ids:
                    notes.append(
                        "DisorderType 'Disease' with children sharing"
                        " same gene(s) -> MONOGENIC (clinical subtypes)"
                    )
        elif preliminary == "PHENOCOPY":
            disease_class = "PHENOCOPY"
            notes.append(
                "DisorderType '%s' -> PHENOCOPY" % disorder_type)
        else:
            disease_class = preliminary

    lookup_strategy = CLASS_TO_STRATEGY.get(disease_class, "UNKNOWN")
    logger.info(
        "  Class: %s / Strategy: %s", disease_class, lookup_strategy)

    logger.info("  Step 5: Gene resolution...")
    gene_set: list[str] = []
    primary_gene = None
    gene_source = None
    conflict_detected = False

    if disease_class in ["MONOGENIC", "PREDISPOSITION"]:
        direct_genes = _get_genes_for_orpha(
            orpha_id_clean, causative_only=True)
        if direct_genes:
            # Detect multiple causative genes BEFORE truncating to the
            # primary. The conflict must be evaluated against the full
            # causative list; testing len() after the [:1] truncation
            # (as a prior version did) could never be true and silently
            # hid every multi-gene MONOGENIC case. Detection only --
            # the first gene is still selected as primary, and the
            # downstream consequence of a conflict is parked with the
            # UNCERTAIN-category work.
            if len(direct_genes) > 1:
                conflict_detected = True
                notes.append(
                    "MONOGENIC disease with %d causative genes %s -- "
                    "first selected as primary; conflict flagged for "
                    "review" % (len(direct_genes), direct_genes)
                )
            gene_set = direct_genes[:1]
            primary_gene = gene_set[0]
            gene_source = "orphadata_genes"
        else:
            omim_gene = _omim_chain(orpha_id_clean)
            if omim_gene:
                gene_set = [omim_gene]
                primary_gene = omim_gene
                gene_source = "omim_chain"
            else:
                notes.append(
                    "No gene found via orphadata or OMIM chain")

    elif disease_class in ["HETEROGENEOUS", "PATHWAY_DISORDER"]:
        gene_set = _get_gene_family(orpha_id_clean)
        primary_gene = None
        gene_source = (
            "orphadata_gene_family" if gene_set else None)
        if not gene_set:
            notes.append("No genes found in child diseases")

    elif disease_class == "PHENOCOPY":
        direct_genes = _get_genes_for_orpha(
            orpha_id_clean, causative_only=True)
        if direct_genes:
            gene_set = direct_genes
            primary_gene = (
                direct_genes[0] if len(direct_genes) == 1 else None)
            gene_source = "orphadata_genes_phenocopy"
        else:
            omim_gene = _omim_chain(orpha_id_clean)
            if omim_gene:
                gene_set = [omim_gene]
                primary_gene = omim_gene
                gene_source = "omim_chain_phenocopy"

    elif disease_class == "SYNDROMIC":
        # causative_only=False is deliberate: for syndromic
        # disease the gene set intentionally includes non-
        # causative (phenotypic-expression / severity) genes.
        # The gene is informational, not an endpoint input, so
        # breadth is safe and desirable here (see resolve_disease
        # docstring).
        direct_genes = _get_genes_for_orpha(
            orpha_id_clean, causative_only=False)
        if direct_genes:
            gene_set = direct_genes
            gene_source = "orphadata_genes_syndromic"
        else:
            omim_gene = _omim_chain(orpha_id_clean)
            if omim_gene:
                gene_set = [omim_gene]
                gene_source = "omim_chain_syndromic"

    logger.info(
        "  Genes: %s%s",
        gene_set[:5] if gene_set else "none",
        "..." if len(gene_set) > 5 else "",
    )

    gene_confidence = _gene_set_confidence(gene_set, mondo_id)

    if (gene_confidence == "LOW"
            and primary_gene
            and _is_eponymous_gene(
                primary_gene, preferred_name or disease_name)):
        gene_confidence = "CONFIRMED"
        notes.append(
            "Eponymous gene upgrade: %s appears in disease name "
            "'%s' -- confidence upgraded from LOW to CONFIRMED"
            % (primary_gene, preferred_name or disease_name)
        )

    if not nom["found"]:
        resolution_status = "NOMENCLATURE_NO_LOCAL_MATCH"
        notes.append(
            "No local nomenclature match -- the live API supplied the "
            "disease name; the local nomenclature snapshot did not "
            "contain this ORPHA ID. Not a blocker: the entry proceeds. "
            "Recorded for calibration so API/local-snapshot drift is "
            "visible and the snapshot can be refreshed.")
    elif conflict_detected:
        resolution_status = "CONFLICT_DETECTED"
    elif gene_set and gene_confidence in ["CONFIRMED", "HIGH"]:
        resolution_status = "RESOLVED"
    elif gene_set:
        resolution_status = "HIGH_CONFIDENCE"
    elif (disease_class in ["HETEROGENEOUS", "PATHWAY_DISORDER"]
          and not gene_set):
        resolution_status = "MODERATE_CONFIDENCE"
        notes.append("Gene family expected but none found")
    else:
        resolution_status = "GENE_NOT_RESOLVED"
        notes.append(
            "No specific gene mapping identified by the system. This "
            "is a valid outcome, not a failure: many rare diseases "
            "are non-genetic (infectious, autoimmune, toxic, other) "
            "and some genetic diseases resolve no gene against the "
            "current reference data. The entry proceeds and is "
            "categorized on trial status. Recorded for calibration "
            "with the disease name so the unresolved-mapping backlog "
            "is visible for manual review.")

    # Neither a missing local nomenclature match nor an unresolved
    # gene mapping is a content error requiring per-disease human
    # review. The first is a local-snapshot staleness condition (the
    # API already supplied the name); the second is a valid outcome
    # (non-genetic disease, or a gene not in the current reference
    # data). Both are routed to calibration instead. Only a genuine
    # multi-gene conflict remains an escalation.
    requires_human_review = resolution_status in [
        "CONFLICT_DETECTED",
    ]

    # Per-run source-file load health (v2.5). Read the health map
    # populated by the loaders exercised above. degraded_files lists
    # any source file that was ABSENT or errored on load this run;
    # a file that loaded fine (even if genuinely empty) is "ok" and a
    # file never exercised has no entry and is not counted. This is a
    # per-run-environment signal stamped identically onto every disease
    # in a run with a degraded file. DETECTION ONLY -- no gene,
    # confidence, class, status, or category value above is affected
    # by it; it only makes a silent file-load failure visible.
    health = get_file_load_health()
    degraded_files = sorted(
        [k for k, v in health.items() if v != "ok"])
    file_load_degraded = bool(degraded_files)
    if file_load_degraded:
        logger.warning(
            "  \u26a0 CALIBRATION: source file load degraded this "
            "run -- %s. Gene confidence may be systematically "
            "depressed across the run; recorded for calibration, not "
            "escalated.",
            ", ".join(
                "%s=%s" % (k, health[k]) for k in degraded_files))

    # gene_identified -- the single, authoritative genetics
    # determination, computed once here where the confidence, class,
    # and gene fields all live, and sealed into the resolved object
    # for every downstream consumer to read. It is NOT re-derived
    # anywhere else: consumers (orchestrator, entry_comparison_core)
    # read this field. A CONFIRMED/HIGH-confidence gene set is
    # identified; a LOW-confidence set is identified only when the
    # class expects it and the gene is actually present (a single gene
    # for MONOGENIC, any gene for the family classes).
    gene_identified = False
    if gene_confidence in ["CONFIRMED", "HIGH"]:
        gene_identified = True
    elif gene_confidence == "LOW":
        if disease_class == "MONOGENIC" and primary_gene:
            gene_identified = True
        elif (disease_class in ["HETEROGENEOUS", "PATHWAY_DISORDER"]
              and gene_set):
            gene_identified = True

    # Sealed once here so consumers read rather than re-derive.
    # is_polygenic is informational (display + the additive-
    # synonym / P+gene label); it gates no determination.
    is_polygenic = (
        disease_class in ["HETEROGENEOUS", "PATHWAY_DISORDER"]
        and len(gene_set) > 1
    )

    resolved_object = {
        "orpha_id": orpha_id_clean,
        "preferred_name": preferred_name,
        "synonyms": synonyms,
        "disorder_type": disorder_type,
        "disease_class": disease_class,
        "lookup_strategy": lookup_strategy,
        "parent_orpha_ids": parent_ids,
        "child_orpha_ids": child_ids,
        "is_subtype": is_subtype,
        "mondo_id": mondo_id,
        "primary_gene": primary_gene,
        "gene_set": gene_set,
        "is_polygenic": is_polygenic,
        "gene_confidence": gene_confidence,
        "gene_identified": gene_identified,
        "gene_source": gene_source,
        "conflict_detected": conflict_detected,
        "resolution_status": resolution_status,
        "requires_human_review": requires_human_review,
        "file_load_degraded": file_load_degraded,
        "degraded_files": degraded_files,
        "file_load_health": health,
        "notes": notes,
        "resolution_date": str(date.today()),
        "agent_version": AGENT_VERSION,
        "source_files": {
            "nomenclature": NOMENCLATURE_FILE,
            "parent_map": PARENT_MAP_FILE,
            "mondo": MONDO_FILE,
            "genes": GENES_FILE,
            "product1": PRODUCT1_FILE,
            "mim2gene": MIM2GENE_FILE,
            "hgnc": HGNC_FILE,
            "clingen": CLINGEN_FILE,
        },
    }

    logger.info(
        "  Status: %s | Confidence: %s",
        resolution_status, gene_confidence,
    )
    if notes:
        for note in notes:
            logger.info("  Note: %s", note)

    return resolved_object


VERIFICATION_CASES = [
    {
        "orpha_id": "355",
        "disease_name": "Gaucher disease",
        "expected_class": "MONOGENIC",
        "expected_strategy": "SINGLE_GENE",
        "expected_primary_gene": "GBA1",
        "note": "Clinical subtypes all caused by GBA1 -- MONOGENIC.",
    },
    {
        "orpha_id": "487",
        "disease_name": "Krabbe disease",
        "expected_class": "MONOGENIC",
        "expected_strategy": "SINGLE_GENE",
        "expected_primary_gene": "GALC",
        "note": "Monogenic. PSAP is a phenocopy subtype.",
    },
    {
        "orpha_id": "607",
        "disease_name": "Nemaline myopathy",
        "expected_class": "HETEROGENEOUS",
        "expected_strategy": "GENE_FAMILY",
        "expected_primary_gene": None,
        "note": "Clinical group -- diverse genes across subtypes.",
    },
    {
        "orpha_id": "561854",
        "disease_name": "FOXG1 syndrome",
        "expected_class": "MONOGENIC",
        "expected_strategy": "SINGLE_GENE",
        "expected_primary_gene": "FOXG1",
        "note": (
            "Eponymous gene -- FOXG1 in disease name -> CONFIRMED."),
    },
    {
        "orpha_id": "500180",
        "disease_name": (
            "Childhood-onset motor and cognitive regression syndrome"
        ),
        "expected_class": "MONOGENIC",
        "expected_strategy": "SINGLE_GENE",
        "expected_primary_gene": "UBTF",
        "note": "Category 4 disease. UBTF gene.",
    },
]


def run_verification() -> list[dict[str, Any]]:
    """Run the verification suite against known test cases."""
    logger.info("\n%s", "=" * 60)
    logger.info(
        "DISEASE RESOLUTION AGENT v%s -- VERIFICATION SUITE",
        AGENT_VERSION)
    logger.info("=" * 60)

    passed = 0
    failed = 0
    results: list[dict[str, Any]] = []

    for case in VERIFICATION_CASES:
        logger.info("\n%s", "=" * 60)
        logger.info(
            "TEST: %s (ORPHA:%s)",
            case["disease_name"], case["orpha_id"],
        )

        resolved = resolve_disease(
            case["orpha_id"], case["disease_name"])

        class_pass = (
            resolved["disease_class"] == case["expected_class"])
        strategy_pass = (
            resolved["lookup_strategy"] == case["expected_strategy"])
        gene_pass = (
            resolved["primary_gene"] == case["expected_primary_gene"])
        overall_pass = class_pass and strategy_pass and gene_pass

        if overall_pass:
            passed += 1
            logger.info("\n  PASS")
        else:
            failed += 1
            logger.info("\n  FAIL")
            if not class_pass:
                logger.info(
                    "    Class: expected %s, got %s",
                    case["expected_class"],
                    resolved["disease_class"],
                )
            if not strategy_pass:
                logger.info(
                    "    Strategy: expected %s, got %s",
                    case["expected_strategy"],
                    resolved["lookup_strategy"],
                )
            if not gene_pass:
                logger.info(
                    "    Gene: expected %s, got %s",
                    case["expected_primary_gene"],
                    resolved["primary_gene"],
                )

        results.append({
            "disease": case["disease_name"],
            "pass": overall_pass,
            "class": resolved["disease_class"],
            "strategy": resolved["lookup_strategy"],
            "primary_gene": resolved["primary_gene"],
            "gene_set": resolved["gene_set"],
            "confidence": resolved["gene_confidence"],
            "status": resolved["resolution_status"],
        })

    logger.info("\n%s", "=" * 60)
    logger.info(
        "RESULTS: %d/5 passed, %d/5 failed", passed, failed)
    logger.info("=" * 60)
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        logger.info(
            "  %s  %-40s  %-20s  gene=%s  %s",
            status,
            r["disease"][:40],
            r["class"],
            r["primary_gene"] or "family",
            r["confidence"],
        )

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_verification()
