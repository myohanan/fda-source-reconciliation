"""
group_measures.py
-----------------
Make a flat list of trial outcome-measure titles readable by grouping
titles that share their first few words under one header.

Simple and deterministic: the header is the first N words of a title.
Titles with the same first N words are grouped together. That is all.
"""

import re


def _norm(title: str) -> str:
    t = title.strip()
    # drop a leading trial-structure prefix so the real measure leads
    t = re.sub(r"^(core phase|part\\s*\\d+\\w*|extension\\s*\\d*|"
               r"cohort\\s*\\d+|period\\s*\\d+[^:\\-]*|double-blind period|"
               r"part\\s*\\d+[a-z]?)\\s*[:\\-]\\s*", "", t, flags=re.I)
    return t.strip()


def _header(title: str, n_words: int) -> str:
    words = _norm(title).split()
    return " ".join(words[:n_words])


def group(titles, n_words=3):
    buckets = {}
    for raw in titles:
        key = _header(raw, n_words).lower()
        buckets.setdefault(key, []).append(_norm(raw))
    # display each header using the actual first-N-words casing of its
    # first member; sort headers by how many titles they hold.
    out = []
    for key, members in buckets.items():
        members = sorted(set(members))
        header = " ".join(members[0].split()[:n_words])
        out.append((header, members))
    out.sort(key=lambda kv: (-len(kv[1]), kv[0].lower()))
    return out


def print_grouped(titles, n_words=3):
    grouped = group(titles, n_words)
    multi = [g for g in grouped if len(g[1]) > 1]
    singles = [g for g in grouped if len(g[1]) == 1]
    print(f"{len(titles)} outcome measures -> "
          f"{len(grouped)} groups by first {n_words} words "
          f"({len(multi)} with 2+ members):")
    print()
    for header, members in grouped:
        if len(members) > 1:
            print(f"{header}  ({len(members)})")
            for m in members:
                print(f"    {m[:74]}")
            print()
    if singles:
        print(f"-- single measures ({len(singles)}) --")
        for header, members in singles:
            print(f"    {members[0][:74]}")


def main():
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    n_words = 3
    for a in sys.argv[1:]:
        if a.startswith("--words="):
            n_words = int(a.split("=")[1])
    if args:
        with open(args[0], encoding="utf-8") as f:
            titles = [ln.rstrip("\\n") for ln in f if ln.strip()]
        print_grouped(titles, n_words)
    else:
        print("usage: python3 group_measures.py titles.txt [--words=N]")


if __name__ == "__main__":
    main()