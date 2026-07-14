"""
term_match_util.py
------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

Shared deterministic term-matching. Single source of truth for the
short-term word-boundary rule, so no two consumers can drift.

Ported from the rare-disease endpoint library (where it was
fda_match_util.py) and renamed, so the two repositories cannot be
confused for one another.

THE RULE

A short search term (<= SHORT_TERM_MAX_LEN characters) matches text only
on a whole-word boundary. A longer term matches as a plain
case-insensitive substring.

The boundary guard exists so a 2-3 character abbreviation does not
substring-match an unrelated record. Without it, "AR" matches "arginase
1 deficiency" -- and in the rare-disease pipeline a false FDA-table
match became a fabricated Category 1: an FDA-validated surrogate
endpoint that never existed. The worst output class the system could
produce.

THE RULE'S LIMIT, STATED PLAINLY

The guard protects SHORT terms. It does NOT protect long ones, which
still match as substrings. So "hip fracture" WILL match "chip fracture
of the talus" -- a real hazard, encountered in this repository while
searching ICD-10.

That is not a defect to fix here. It is the reason the resolver does
not rely on substring matching for identity at all: identity is
resolved against controlled vocabularies, where a concept has a code.
This utility is for matching a known term against free text -- indication
prose, an endpoint description -- where no code exists and there is
nothing better available.

Use it where there is no vocabulary. Never use it where there is one.

CONTRACT
- `text` is assumed already lowercased by the caller.
- `term` is lowercased here defensively.
- One-directional: does `term` appear in `text`.

No model call. No network. Pure string logic.
"""

import re

SHORT_TERM_MAX_LEN: int = 4


def term_matches(term: str, text: str) -> bool:
    """
    Does `term` appear in `text`?

    Short terms require a whole-word boundary. Long terms may match as
    a substring -- see the docstring's note on that limit.
    """
    if not term or not text:
        return False

    term = term.lower().strip()
    if not term:
        return False

    if len(term) <= SHORT_TERM_MAX_LEN:
        pattern = r"\b" + re.escape(term) + r"\b"
        return re.search(pattern, text) is not None

    return term in text
