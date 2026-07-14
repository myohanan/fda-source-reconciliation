"""
measure_hierarchy.py
--------------------
FDA Source Reconciliation
Independent Women's Center for Better Health

WHICH SOURCES CAN SUPPLY A HIERARCHY, FOR WHICH CONDITIONS?

This is a MEASUREMENT, not a build. It exists because the first attempt
at a hierarchy_matcher was built on SNOMED alone -- not because SNOMED
was the right authority, but because it was the one already on hand.
The gaps were then defended instead of measured.

The neighbor question is real: a developer types "congestive heart
failure," gets NO COA, and the KCCQ -- qualified, used in 1,029 trials,
117 as a primary endpoint -- is one SIBLING away under the same parent.
An answer of "nothing" is honest and nearly useless.

But a hierarchy that silently cannot look for some conditions is worse
than none, because "no neighbors" and "we could not check" are
different facts and a user cannot tell them apart.

So: measure. For all 54 catalog conditions, ask EVERY source that has a
hierarchy whether it can supply a parent.

  SNOMED    clinical subsumption, via UMLS source hierarchy
  MeSH      tree numbers -- the position IS the hierarchy
  MONDO     the research disease taxonomy, on disk
  ICD-10    chapter/block structure
  NCIt      the NCI thesaurus hierarchy
  MedDRA    five-level regulatory hierarchy

Then we will KNOW whether the neighbor feature works for 46 of 54 or
for 54 -- instead of guessing, defending, and being caught.
"""
import csv
import json
import time
import urllib.parse
import urllib.request

import condition_resolver as cr

RESOLUTION = "fda_data/coa_resolution.csv"
OUTPUT = "fda_data/hierarchy_coverage.csv"

UMLS = "https://uts-ws.nlm.nih.gov/rest"
H = {"User-Agent": "fda-recon/1.0", "Accept": "application/json"}
PAUSE = 0.12

# Sources with a real is-a hierarchy, and their UMLS abbreviation.
SOURCES = {
    "SNOMED": "SNOMEDCT_US",
    "MESH": "MSH",
    "NCIT": "NCI",
    "MEDDRA": "MDR",
    "ICD10CM": "ICD10CM",
}

COLUMNS = ["condition", "cui", "label", "status"] + [
    f"{s}_{k}" for s in SOURCES for k in ("code", "parents")
] + ["n_sources_with_hierarchy", "mondo_id", "mondo_parents"]


def get(path, **params):
    params["apiKey"] = cr.UMLS_API_KEY
    url = f"{UMLS}{path}?{urllib.parse.urlencode(params)}"
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=H), timeout=40))


def code_in(cui, sab):
    """The source's own code for this concept, if it has one."""
    try:
        atoms = get(f"/content/current/CUI/{cui}/atoms",
                    sabs=sab, pageSize=5)["result"]
    except Exception:
        return ""
    time.sleep(PAUSE)
    for a in atoms:
        raw = a.get("code", "")
        if raw:
            return raw.rstrip("/").split("/")[-1]
    return ""


def parents_of(sab, code):
    """How many parents does this source give the concept?"""
    if not code:
        return -1
    try:
        r = get(f"/content/current/source/{sab}/{code}/parents",
                pageSize=25)["result"]
    except Exception:
        return 0
    time.sleep(PAUSE)
    return len(r)


# MONDO's hierarchy is on disk
mondo_parents = {}
with open("fda_data/mondo_resolution_index.csv", newline="",
          encoding="utf-8") as f:
    for row in csv.DictReader(f):
        mondo_parents[row["mondo_id"]] = len(
            [p for p in row["parents"].split("|") if p])

rows = list(csv.DictReader(open(RESOLUTION, newline="",
                                encoding="utf-8")))
print(f"conditions: {len(rows)}")
print()

out = []
for i, r in enumerate(rows, 1):
    rec = {
        "condition": r["condition"],
        "cui": r["cui"],
        "label": r["label"],
        "status": r["status"],
        "mondo_id": r["mondo_id"],
        "mondo_parents": mondo_parents.get(r["mondo_id"], 0)
        if r["mondo_id"] else 0,
    }

    n_with = 0
    if r["cui"]:
        for name, sab in SOURCES.items():
            code = code_in(r["cui"], sab)
            n_par = parents_of(sab, code) if code else 0
            rec[f"{name}_code"] = code
            rec[f"{name}_parents"] = max(n_par, 0)
            if code and n_par > 0:
                n_with += 1
    else:
        for name in SOURCES:
            rec[f"{name}_code"] = ""
            rec[f"{name}_parents"] = 0

    if rec["mondo_parents"] > 0:
        n_with += 1
    rec["n_sources_with_hierarchy"] = n_with
    out.append(rec)

    if i % 10 == 0 or i == len(rows):
        print(f"  {i}/{len(rows)}")

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(out)

print()
print("=" * 68)
print("HIERARCHY COVERAGE, PER SOURCE")
print("=" * 68)
n = len(out)
for name in list(SOURCES) + ["MONDO"]:
    key = f"{name}_parents" if name != "MONDO" else "mondo_parents"
    have = sum(1 for r in out if r.get(key, 0) > 0)
    pct = 100 * have // n
    print(f"  {name:<8} {have:>3}/{n}  ({pct:>3}%)  "
          f"{'#' * (pct // 3)}")

print()
print("=" * 68)
print("HOW MANY SOURCES GIVE EACH CONDITION A PARENT?")
print("=" * 68)
dist = {}
for r in out:
    k = r["n_sources_with_hierarchy"]
    dist[k] = dist.get(k, 0) + 1
for k in sorted(dist):
    print(f"  {k} source(s)  {dist[k]:>3}  {'#' * dist[k]}")

print()
print("=" * 68)
print("NO HIERARCHY AT ALL -- from any source")
print("=" * 68)
none = [r for r in out if r["n_sources_with_hierarchy"] == 0]
for r in none:
    print(f'  [{r["status"]:<28}] {r["condition"][:44]}')
print()
print(f"  {len(none)} of {n} conditions have NO hierarchy anywhere.")
print()
print(f"Wrote {OUTPUT}")
