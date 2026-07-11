"""
download_coa_documents.py
-------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Downloads the public COA qualification submission documents.

Under section 507 of the FD&C Act (created by the 21st Century Cures
Act), FDA must publicly post COA qualification submissions (Letter of
Intent, Qualification Plan, Full Qualification Package) and its own
determination letters in response. Those documents are NOT on the
submissions summary table, and they are NOT reachable via the DDT
project records' appianDocIds (those are internal EDM identifiers that
do not resolve publicly). They live on a per-COA landing page, one page
per DDT COA number, each linking its documents as ordinary
fda.gov/media/NNNNN/download PDFs.

This script runs in two stages:

  Stage 1 (index): crawl the COA submissions page and the qualified-COAs
    page, collect every per-COA landing page, visit each, and record
    every document link with its label ("Letter of Intent", "FDA
    Response (Accepted)", "Qualification Plan", etc). Writes
    fda_data/coa_documents_index.csv. Fast, no PDFs downloaded.

  Stage 2 (download): fetch each PDF from the index into
    fda_data/coa_documents/. Writes incrementally and skips files
    already on disk, so an interrupted run resumes rather than
    restarting.

The paired structure is the point: each COA has the requestor's
submission AND FDA's written determination -- and in many cases FDA's
own Clinical Review, Biostatistics Review, and SEALD Review. That is a
labeled corpus: the sponsor's argument and the regulator's analysis,
side by side.

Politeness: fda.gov is a normal web server, not a rate-limited API.
This script pauses between requests and identifies itself. Do not
remove the pause.
"""

import csv
import os
import re
import time
import urllib.error
import urllib.request

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "fda_data")
INDEX_FILE = os.path.join(DATA_DIR, "coa_documents_index.csv")
DOC_DIR = os.path.join(DATA_DIR, "coa_documents")

FDA_ROOT = "https://www.fda.gov"
SUBMISSIONS_URL = (
    FDA_ROOT + "/drugs/clinical-outcome-assessment-coa-qualification-"
    "program/clinical-outcome-assessments-coa-qualification-program-"
    "submissions")
QUALIFIED_URL = (
    FDA_ROOT + "/drugs/clinical-outcome-assessment-coa-qualification-"
    "program/qualified-clinical-outcome-assessments-coa")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

REQUEST_PAUSE_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 60

INDEX_COLUMNS = [
    "coa_number",
    "coa_slug",
    "landing_page",
    "document_label",
    "document_url",
    "media_id",
    "filename",
]

_LANDING_RE = re.compile(
    r'href="(/drugs/clinical-outcome-assessment-coa-qualification-'
    r'program/ddt-coa-[^"#]+)"')
_ANCHOR_RE = re.compile(
    r'<a[^>]+href="(/media/(\d+)/download[^"]*)"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_COA_NUM_RE = re.compile(r"ddt-coa-(\d+|\d{4}-\d+)")


def _get(url: str) -> str:
    """Fetch a URL as text, with a browser-like User-Agent."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", errors="ignore")


def _clean_label(raw_html: str) -> str:
    """Strip tags/whitespace from an anchor's inner HTML."""
    text = _TAG_RE.sub("", raw_html)
    return " ".join(text.split()).strip()


def collect_landing_pages() -> list[str]:
    """Return every per-COA landing page path, deduplicated."""
    paths = set()
    for index_url in (SUBMISSIONS_URL, QUALIFIED_URL):
        html = _get(index_url)
        for path in _LANDING_RE.findall(html):
            paths.add(path)
        time.sleep(REQUEST_PAUSE_SECONDS)
    return sorted(paths)


def index_documents(landing_paths: list[str]) -> list[dict]:
    """Visit each landing page; record every document link found."""
    rows = []
    total = len(landing_paths)
    for position, path in enumerate(landing_paths, start=1):
        slug = path.rsplit("/", 1)[-1]
        match = _COA_NUM_RE.search(slug)
        coa_number = match.group(1) if match else ""
        url = FDA_ROOT + path
        try:
            html = _get(url)
        except urllib.error.HTTPError as exc:
            print(f"  [{position}/{total}] {slug}: HTTP {exc.code}")
            time.sleep(REQUEST_PAUSE_SECONDS)
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"  [{position}/{total}] {slug}: {type(exc).__name__}")
            time.sleep(REQUEST_PAUSE_SECONDS)
            continue

        found = 0
        for href, media_id, inner in _ANCHOR_RE.findall(html):
            label = _clean_label(inner)
            if not label:
                label = "(unlabeled)"
            safe_label = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")
            filename = f"COA_{coa_number}_{media_id}_{safe_label}.pdf"
            rows.append({
                "coa_number": coa_number,
                "coa_slug": slug,
                "landing_page": url,
                "document_label": label,
                "document_url": FDA_ROOT + href,
                "media_id": media_id,
                "filename": filename,
            })
            found += 1

        print(f"  [{position}/{total}] COA {coa_number}: {found} documents")
        time.sleep(REQUEST_PAUSE_SECONDS)
    return rows


def download_documents(rows: list[dict]) -> None:
    """Download each indexed PDF; skip files already present."""
    os.makedirs(DOC_DIR, exist_ok=True)
    total = len(rows)
    downloaded = 0
    skipped = 0
    failed = 0

    for position, row in enumerate(rows, start=1):
        target = os.path.join(DOC_DIR, row["filename"])
        if os.path.exists(target) and os.path.getsize(target) > 0:
            skipped += 1
            continue
        try:
            request = urllib.request.Request(
                row["document_url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(
                    request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = response.read()
            with open(target, "wb") as handle:
                handle.write(payload)
            downloaded += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED {row['filename']}: {type(exc).__name__}")
            failed += 1
        if position % 25 == 0 or position == total:
            print(f"  {position}/{total} "
                  f"(downloaded {downloaded}, skipped {skipped}, "
                  f"failed {failed})")
        time.sleep(REQUEST_PAUSE_SECONDS)

    print(f"Downloaded {downloaded}, skipped {skipped} (already present), "
          f"failed {failed}.")


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    print("Stage 1: finding COA landing pages...")
    landing_paths = collect_landing_pages()
    print(f"Found {len(landing_paths)} COA landing pages.")
    print()

    print("Stage 1: indexing documents on each landing page...")
    rows = index_documents(landing_paths)
    print()

    with open(INDEX_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote index of {len(rows)} documents to {INDEX_FILE}")

    labels = {}
    for row in rows:
        labels[row["document_label"]] = labels.get(
            row["document_label"], 0) + 1
    print("Document types found:")
    for label, count in sorted(
            labels.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {count:4d}  {label}")
    print()

    print("Stage 2: downloading documents...")
    download_documents(rows)
    print()
    print(f"Documents are in {DOC_DIR}")


if __name__ == "__main__":
    main()
