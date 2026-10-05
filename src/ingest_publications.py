"""Resolve volunteers to OpenAlex authors and pull their top publications.

For each volunteer with a real name, search OpenAlex, score the candidate
authors, accept the best only if it clears a strict graphics/CS topic gate, and
fetch their top works. Reliability-first: name search alone is unreliable (common
names match prolific wrong-field authors), so a candidate must look like a
graphics/CS/digital-art researcher (curated topic allow-list) AND be corroborated
by either an institution match (vs our education/roles) or a solid works count.
Uncertain matches go to a review file and are NOT attached to the cards.

Outputs:
    data/publications/<id>.json   -- per-person cache (chosen author + candidates + works)
    data/publications_review.txt  -- medium-confidence matches for human review
    data/volunteers.json          -- rebuilt via aggregate.py, which attaches a compact
                                     `publications` block for high-confidence caches

Stdlib only (urllib); runs without the venv. Idempotent: skips cached people
unless --force. Polite to OpenAlex (mailto + paced).

Usage:
    python3 src/ingest_publications.py
    python3 src/ingest_publications.py --force
    python3 src/ingest_publications.py --only jdoe
    python3 src/ingest_publications.py --limit 10
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from aggregate import aggregate

ROOT = Path(__file__).resolve().parent.parent
AGG = ROOT / "data" / "volunteers.json"
PUB_DIR = ROOT / "data" / "publications"
REVIEW = ROOT / "data" / "publications_review.txt"

OPENALEX = "https://api.openalex.org"
MAILTO = os.environ["OPENALEX_MAILTO"]   # your email, for OpenAlex's "polite pool"
TOP_WORKS = 5
PACE = 0.34                          # seconds between API calls (stay under OpenAlex limits)
ACCEPT_WORKS = 30                    # works needed to auto-accept a strong-topic match w/o inst

# A candidate must have one of these in its top-3 OpenAlex topics to count as a
# graphics/CS/digital-art researcher. Curated phrases (not loose substrings) so
# physics/materials/neuro/climate namesakes are rejected.
STRONG_TOPICS = (
    "computer graphics", "graphics and visualization", "shape modeling", "3d shape",
    "shape analysis", "human motion and animation", "animation", "rendering",
    "computational geometry", "mesh generation", "geometry processing", "surface reconstruction",
    "virtual reality", "augmented reality", "mixed reality", "immersive",
    "data visualization", "visualization techniques", "scientific visualization",
    "computer vision", "vision and imaging", "image processing", "image synthesis",
    "human-computer interaction", "point cloud", "3d surveying", "art, technology",
    "computational design", "architecture and computational", "aesthetic perception",
    "game design", "game development", "neural rendering", "motion capture",
    "physically based", "fluid simulation", "character animation", "digital fabrication",
    "appearance", "texture synthesis", "shading", "interactive media", "digital media",
)
# Generic words stripped before institution-token matching.
INST_STOP = {
    "university", "college", "institute", "institutes", "school", "department",
    "of", "the", "and", "for", "science", "sciences", "arts", "art", "bachelor",
    "master", "masters", "phd", "doctor", "technology", "engineering", "studies",
    "state", "national", "center", "centre", "research", "laboratory", "lab",
    "studio", "studios", "inc", "llc", "ltd", "company", "academy",
}


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "siggraph-vdc/0.1"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                ra = e.headers.get("Retry-After")
                time.sleep(float(ra) if (ra and ra.isdigit()) else 5 * (attempt + 1))
                continue
            if attempt == 4:
                raise
            time.sleep(1.0 + attempt)
        except Exception:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(1.0 + attempt)
    return {}


def search_authors(name: str) -> list[dict]:
    q = urllib.parse.urlencode({
        "search": name, "per_page": 5, "mailto": MAILTO,
        "select": "id,display_name,orcid,works_count,cited_by_count,last_known_institutions,topics",
    })
    return http_json(f"{OPENALEX}/authors?{q}").get("results", [])


def fetch_works(author_id: str) -> list[dict]:
    aid = author_id.replace("https://openalex.org/", "")
    q = urllib.parse.urlencode({
        "filter": f"author.id:{aid}", "per_page": TOP_WORKS, "sort": "cited_by_count:desc",
        "mailto": MAILTO, "select": "title,display_name,publication_year,primary_location,doi,cited_by_count",
    })
    out = []
    for w in http_json(f"{OPENALEX}/works?{q}").get("results", []):
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        out.append({
            "title": html.unescape(w.get("title") or w.get("display_name") or "(untitled)"),
            "venue": html.unescape(src.get("display_name")) if src.get("display_name") else None,
            "year": w.get("publication_year"),
            "doi": w.get("doi"),
            "citations": w.get("cited_by_count") or 0,
        })
    return out


def toks(strings: list[str]) -> set[str]:
    s = set()
    for t in strings:
        for w in re.findall(r"[a-z]{4,}", (t or "").lower()):
            if w not in INST_STOP:
                s.add(w)
    return s


def norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def cand_insts(a: dict) -> list[str]:
    return [i.get("display_name") for i in (a.get("last_known_institutions") or []) if i.get("display_name")]


def cand_topics(a: dict) -> list[str]:
    return [t.get("display_name") for t in (a.get("topics") or [])[:4] if t.get("display_name")]


def is_strong(topics: list[str]) -> str | None:
    """Return the matched strong topic from the top 3, else None."""
    for t in topics[:3]:
        tl = (t or "").lower()
        if any(s in tl for s in STRONG_TOPICS):
            return t
    return None


def score(a: dict, name: str, person_toks: set[str]) -> dict:
    topics = cand_topics(a)
    strong = is_strong(topics)
    insts = cand_insts(a)
    common = person_toks & toks(insts)
    inst_hit = sorted(common)[0] if common else None
    wc = a.get("works_count") or 0
    name_exact = norm(a.get("display_name")) == norm(name)
    return {
        "openalex_id": (a.get("id") or "").replace("https://openalex.org/", ""),
        "openalex_url": a.get("id"),
        "orcid": a.get("orcid"),
        "display_name": a.get("display_name"),
        "works_count": wc,
        "cited_by_count": a.get("cited_by_count") or 0,
        "institutions": insts,
        "topics": topics,
        "strong_topic": strong,
        "inst_hit": inst_hit,
        "name_exact": name_exact,
        # rank: prefer a real graphics match over a prolific wrong-field namesake
        "rank": [1 if strong else 0, 1 if inst_hit else 0, 1 if name_exact else 0, wc],
    }


def confidence_of(c: dict | None) -> str:
    if not c:
        return "none"
    if c["strong_topic"] and (c["inst_hit"] or c["works_count"] >= ACCEPT_WORKS):
        return "high"
    if c["strong_topic"] or c["inst_hit"]:
        return "medium"
    return "low"


def rescore_candidate(c: dict, name: str, person_toks: set[str]) -> dict:
    """Recompute a cached candidate's signals from its stored raw fields (topics,
    institutions, works_count) — no API call. Works on either cache schema."""
    c = dict(c)
    c["strong_topic"] = is_strong(c.get("topics") or [])
    common = person_toks & toks(c.get("institutions") or [])
    c["inst_hit"] = sorted(common)[0] if common else None
    c["name_exact"] = norm(c.get("display_name")) == norm(name)
    wc = c.get("works_count") or 0
    c["rank"] = [1 if c["strong_topic"] else 0, 1 if c["inst_hit"] else 0,
                 1 if c["name_exact"] else 0, wc]
    return c


def db_people(payload: dict) -> list[dict]:
    out = []
    for p in payload["volunteers"]:
        name = p.get("name")
        edu, roles, loc = [], [], []
        for ex in (p.get("extractions") or {}).values():
            if (not name or name == "Unknown") and ex.get("name") and ex["name"] != "Unknown":
                name = ex["name"]
            edu += ex.get("education") or []
            roles += ex.get("roles") or []
            if ex.get("location"):
                loc.append(ex["location"])
        out.append({"id": p["id"], "name": name, "signal": toks(edu + roles + loc)})
    return out


def resolve(person: dict) -> dict:
    cands = sorted(
        (score(a, person["name"], person["signal"]) for a in search_authors(person["name"])),
        key=lambda c: c["rank"], reverse=True,
    )
    best = cands[0] if cands else None
    conf = confidence_of(best)
    rec = {"id": person["id"], "name": person["name"], "confidence": conf,
           "chosen": best, "candidates": cands, "works": []}
    if best and conf == "high":
        time.sleep(PACE)
        rec["works"] = fetch_works(best["openalex_id"])
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", help="single volunteer id")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rescore", action="store_true",
                    help="recompute confidence from cached candidates (no author API calls)")
    args = ap.parse_args()

    PUB_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(AGG.read_text())
    people = db_people(payload)
    if args.only:
        people = [p for p in people if p["id"] == args.only]
    if args.limit:
        people = people[: args.limit]
    sig = {p["id"]: p for p in people}

    cache: dict[str, dict] = {}
    counts = {"high": 0, "medium": 0, "low": 0, "none": 0, "skip": 0}
    todo = [p for p in people if p["name"] and p["name"] != "Unknown"]
    mode = "Re-scoring cached candidates for" if args.rescore else "Resolving"
    print(f"{mode} {len(todo)} named volunteers...\n")

    for i, p in enumerate(todo, 1):
        out = PUB_DIR / f"{p['id']}.json"
        if args.rescore:
            if not out.exists():
                continue
            rec = json.loads(out.read_text())
            cands = sorted((rescore_candidate(c, p["name"], p["signal"]) for c in rec.get("candidates", [])),
                           key=lambda c: c["rank"], reverse=True)
            best = cands[0] if cands else None
            rec["candidates"] = cands
            rec["chosen"] = best
            rec["confidence"] = confidence_of(best)
            if rec["confidence"] == "high" and best and not rec.get("works"):
                time.sleep(PACE)
                rec["works"] = fetch_works(best["openalex_id"])
            out.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        elif out.exists() and not args.force:
            rec = json.loads(out.read_text())
            counts["skip"] += 1
        else:
            time.sleep(PACE)
            try:
                rec = resolve(p)
            except Exception as e:  # noqa: BLE001
                print(f"[{i:3}/{len(todo)}] ERR  {p['name']}: {type(e).__name__}: {e}")
                continue
            out.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        cache[p["id"]] = rec
        counts[rec["confidence"]] = counts.get(rec["confidence"], 0) + 1
        c = rec.get("chosen") or {}
        flag = {"high": "OK  ", "medium": "?   ", "low": "--  ", "none": "--  "}[rec["confidence"]]
        topic = (c.get("strong_topic") or "")[:30]
        extra = f"{c.get('works_count', 0)}w {topic}" if c else "(no candidate)"
        print(f"[{i:3}/{len(todo)}] {flag}{p['name'][:26]:26} {rec['confidence']:6} {extra}")

    # review file for medium matches — derived from ALL caches on disk, so
    # partial runs (--only / --limit) don't clobber the queue
    med = [r for r in (json.loads(f.read_text()) for f in sorted(PUB_DIR.glob("*.json")))
           if r.get("confidence") == "medium"]
    lines = [f"PUBLICATION MATCHES NEEDING REVIEW ({len(med)})",
             "Medium confidence: a strong-topic OR institution hit, but not both/enough.", ""]
    for r in sorted(med, key=lambda r: r["name"].lower()):
        c = r["chosen"] or {}
        lines.append(f"{r['name']}  ({r['id']})")
        lines.append(f"   best: {c.get('display_name')}  {c.get('openalex_id')}  "
                     f"{c.get('works_count')}w  strong={c.get('strong_topic')}  inst={c.get('inst_hit')}")
        lines.append(f"   inst: {', '.join(c.get('institutions') or []) or '—'}")
        lines.append(f"   topics: {', '.join(c.get('topics') or []) or '—'}")
        lines.append(f"   page: {c.get('openalex_url')}")
        lines.append("")
    REVIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nhigh={counts['high']} medium={counts['medium']} low={counts['low']} "
          f"none={counts['none']} (skipped-cached={counts['skip']})")
    print(f"review {len(med)} medium matches -> {REVIEW.relative_to(ROOT)}")
    aggregate()


if __name__ == "__main__":
    main()
