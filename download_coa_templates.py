"""
download_coa_templates.py
-------------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Downloads the FDA COA qualification templates and governing guidance.

These are the QUESTION LIBRARY for any COA-submission review work:
the numbered required-section lists a submission must satisfy. They
are the COA-domain equivalent of CONSORT for trial reports -- the
checklist is not invented, it is FDA's own published template.

  fda_117148.pdf  Letter of Intent (LOI) template. Sections 1-4 are
                  the publicly-posted portion under FD&C Act 507.
  fda_123245.pdf  Qualification Plan (QP) template, March 2021.
  fda_147023.pdf  Qualification Plan (QP) template, May 2021 (newer).
                  Fully enumerated required sections:
                    1.1-1.5  introduction, concept of interest,
                             context of use, COA details, expertise
                    3.1-3.8  literature review, expert input,
                             respondent input, concept elicitation,
                             item generation, cognitive interviews,
                             item finalization, conceptual framework
                    4.1-4.2  study design, inclusion/exclusion,
                             assessment timing, sample size and
                             justification, baseline characteristics,
                             item-level statistics, dimensionality,
                             item reduction decisions
                  Each numbered subsection is a completeness-check
                  item: present/absent is deterministic. Section 3.1
                  (literature review with cited publications) is where
                  citation-integrity and claim-verification attach.
  fda_133511.pdf  Qualification Process for Drug Development Tools --
                  the governing guidance. Defines the LOI/QP/FQP
                  stages, the review process, and the "reviewable"
                  determination (the completeness assessment that
                  precedes the review clock).
  fda_151216.pdf  COAQP information session slides. Contains the
                  published review clocks: LOI 3 months, QP 6 months,
                  FQP 10 months -- and notes the clock does not start
                  until the submission is deemed reviewable.
  fda_133337.pdf  EDM submission portal reference guide (how
                  requestors submit; context, not a checklist).

The PDFs are gitignored (re-downloadable). This script is the record.
"""

import os
import urllib.request

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(_BASE_DIR, "fda_data", "coa_templates")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MEDIA_IDS = {
    "117148": "Letter of Intent (LOI) template",
    "123245": "Qualification Plan (QP) template, March 2021",
    "147023": "Qualification Plan (QP) template, May 2021",
    "133511": "Qualification Process for Drug Development Tools",
    "151216": "COAQP information session slides (review clocks)",
    "133337": "EDM submission portal reference guide",
}


def main() -> None:
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    for media_id, description in MEDIA_IDS.items():
        target = os.path.join(TEMPLATE_DIR, f"fda_{media_id}.pdf")
        url = f"https://www.fda.gov/media/{media_id}/download"
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
            if not payload.startswith(b"%PDF"):
                print(f"  {media_id}: NOT A PDF -- skipped")
                continue
            with open(target, "wb") as handle:
                handle.write(payload)
            print(f"  {media_id}: {len(payload):>8} bytes -- {description}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {media_id}: FAILED ({type(exc).__name__})")

    print()
    print(f"Templates are in {TEMPLATE_DIR}")


if __name__ == "__main__":
    main()
