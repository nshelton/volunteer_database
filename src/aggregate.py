"""Build data/volunteers.json — the ONLY writer of that file.

Deterministic merge of:
    data/extracted/<model>/<id>.json   -- per-model LLM extractions
    data/records.json                  -- provenance (url / section / source_type)
    data/gdrive_headings.json          -- curated gdrive names / headings / summaries
    data/publications/<id>.json        -- OpenAlex caches (high-confidence attach)

volunteers.json is a pure function of those inputs, so the scripts that refresh
them (extract.py, extract_gdrive.py, ingest_gdrive.py, ingest_publications.py)
can run in any order — each just re-aggregates when done. Stdlib only.

Usage:
    python3 src/aggregate.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "data" / "records.json"
EXTRACT_ROOT = ROOT / "data" / "extracted"   # one subdir per model
GDRIVE_CACHE = ROOT / "data" / "gdrive_headings.json"
PUB_DIR = ROOT / "data" / "publications"
AGG = ROOT / "data" / "volunteers.json"

# Fields produced by the extraction model (everything else is shared provenance).
EXTRACTION_FIELDS = (
    "name", "headline", "summary", "location", "seniority", "years_experience",
    "categories", "skills", "tools", "roles", "education",
    "is_personal_profile", "data_quality",
)


def aggregate() -> None:
    records = {r["id"]: r for r in json.loads(RECORDS.read_text())}
    gdrive = json.loads(GDRIVE_CACHE.read_text()) if GDRIVE_CACHE.exists() else {}
    people: dict[str, dict] = {}
    models: list[str] = []

    def person(rid: str) -> dict:
        rec = records.get(rid, {})
        gd = "gdrive" if rid in gdrive else None
        return people.setdefault(rid, {
            "id": rid,
            "url": rec.get("url"),
            "section": rec.get("section") or gd,
            "source_type": rec.get("source_type") or gd,
            "extractions": {},
        })

    for mdir in sorted(p for p in EXTRACT_ROOT.iterdir() if p.is_dir()):
        for f in sorted(mdir.glob("*.json")):
            d = json.loads(f.read_text())
            model = d.get("model", mdir.name)
            if model not in models:
                models.append(model)
            person(d["id"])["extractions"][model] = {k: d.get(k) for k in EXTRACTION_FIELDS}

    for rid, gd in gdrive.items():
        v = person(rid)
        v["name"] = gd["name"]
        v["gdrive_headings"] = gd["headings"]
        v["gdrive_summary"] = gd["summary"]

    attached = 0
    for f in sorted(PUB_DIR.glob("*.json")) if PUB_DIR.is_dir() else []:
        rec = json.loads(f.read_text())
        c = rec.get("chosen")
        if rec.get("confidence") == "high" and c and f.stem in people:
            people[f.stem]["publications"] = {
                "openalex_id": c["openalex_id"], "openalex_url": c["openalex_url"],
                "orcid": c.get("orcid"), "confidence": "high",
                "works_count": c.get("works_count"), "works": rec.get("works", []),
            }
            attached += 1

    payload = {"models": models, "volunteers": list(people.values())}
    AGG.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Aggregated {len(people)} volunteers across {len(models)} model(s) {models}, "
          f"{len(gdrive)} gdrive docs, {attached} publication blocks -> {AGG.relative_to(ROOT)}")


if __name__ == "__main__":
    aggregate()
