"""Pull the section headings from each data/gdrive/<Name>.docx into the
data/gdrive_headings.json cache.

The teammate's gdrive summaries use Word Heading paragraphs for their numbered
sections (e.g. "1. 3D Graphics Engineering & Architecture"). Those heading titles
are an already-curated list of skill themes per person, so we just extract them --
no LLM. Docs that match an existing volunteer (see ALIAS) enrich that record; the
rest become new headings-only volunteers (slugified name). aggregate.py folds the
cache into data/volunteers.json — this script rebuilds the cache, then re-aggregates.

Outputs:
    data/gdrive_headings.json   -- cache: { id: {name, headings, summary} }
    data/volunteers.json        -- rebuilt via aggregate.py

Stdlib only; runs without the venv or the LLM. Idempotent, order-free.

Usage:
    python3 src/ingest_gdrive.py
    python3 src/ingest_gdrive.py --dry-run     # print headings + mapping, no writes
"""
from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from pathlib import Path

from aggregate import aggregate

ROOT = Path(__file__).resolve().parent.parent
GDRIVE_DIR = ROOT / "data" / "gdrive"
CACHE = ROOT / "data" / "gdrive_headings.json"

# gdrive filename stem -> existing volunteer id, for docs whose person already
# has a record that name-matching can't find. Docs not listed become new
# headings-only volunteers. Real names, so it lives with the data, not in git.
ALIAS: dict[str, str] = json.loads((ROOT / "data" / "gdrive_aliases.json").read_text())

_T = re.compile(r"<w:t\b[^>]*>(.*?)</w:t>", re.S)            # avoids <w:top>, <w:tbl...>
_STYLE = re.compile(r'<w:pStyle w:val="([^"]+)"')
_NUMPREFIX = re.compile(r"^\s*\d+[.)]\s*")
_SKIP = {"summary of skills"}


def parse_headings(path: Path) -> list[str]:
    """Titles of Heading-styled paragraphs, number prefix stripped."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    out = []
    for block in re.findall(r"<w:p\b.*?</w:p>", xml, re.S):
        style = _STYLE.search(block)
        if not style or not style.group(1).lower().startswith("heading"):
            continue
        text = _NUMPREFIX.sub("", html.unescape("".join(_T.findall(block))).strip())
        if text and text.lower() not in _SKIP:
            out.append(text)
    return out


def parse_full_text(path: Path) -> str:
    """All visible paragraph text — the full curated summary prose."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paras = []
    for block in re.findall(r"<w:p\b.*?</w:p>", xml, re.S):
        text = html.unescape("".join(_T.findall(block))).strip()
        if text:
            paras.append(text)
    return "\n".join(paras)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def resolve_id(stem: str) -> str:
    return ALIAS.get(stem, slugify(stem))


def build_cache() -> dict[str, dict]:
    cache = {}
    for p in sorted(GDRIVE_DIR.glob("*.docx")):
        cache[resolve_id(p.stem)] = {"name": p.stem, "headings": parse_headings(p),
                                     "summary": parse_full_text(p)}
    return cache


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print headings + id mapping, write nothing")
    args = ap.parse_args()

    cache = build_cache()
    total = sum(len(g["headings"]) for g in cache.values())

    if args.dry_run:
        for rid, g in sorted(cache.items()):
            print(f"\n### {g['name']}  ->  {rid}  ({len(g['headings'])})")
            for h in g["headings"]:
                print(f"   - {h}")
        print(f"\n{len(cache)} docs, {total} headings")
        return

    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"gdrive: {len(cache)} docs, {total} headings -> {CACHE.relative_to(ROOT)}")
    aggregate()


if __name__ == "__main__":
    main()
