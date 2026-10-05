"""Export a model-comparison CSV from data/volunteers.json.

One row per volunteer, with the data source and — in separate cells per model —
the inferred skill categories and free-form skills. Lets us (and the committee)
compare the local models (Gemma, Qwen) against each other and against the
Gemini/NotebookLM approach.

Output: data/skills_comparison.csv

Columns: id, name, source_url, source_type, section, then per model:
    <model>_name, <model>_categories, <model>_skills
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from taxonomy import CATEGORIES

ROOT = Path(__file__).resolve().parent.parent
AGG = ROOT / "data" / "volunteers.json"
OUT = ROOT / "data" / "skills_comparison.csv"


def label(key: str) -> str:
    return CATEGORIES.get(key, (key,))[0]


def fmt_categories(ex: dict | None) -> str:
    if not ex or ex.get("data_quality") == "not_a_profile":
        return "(insufficient / not a profile)" if ex else ""
    cats = ex.get("categories") or []
    return "; ".join(
        f"{label(c['category'])} ({c.get('level', '')})".replace(" ()", "")
        for c in cats
    )


def fmt_skills(ex: dict | None) -> str:
    if not ex or ex.get("data_quality") == "not_a_profile":
        return ""
    seen, out = set(), []
    for s in (ex.get("skills") or []) + (ex.get("tools") or []):
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return "; ".join(out)


def best_name(extractions: dict, models: list[str]) -> str:
    for m in models:
        n = (extractions.get(m) or {}).get("name") or ""
        if n and n != "Unknown":
            return n
    return "Unknown"


def short(model: str) -> str:
    return model.split(":")[0]


def main() -> None:
    payload = json.loads(AGG.read_text())
    models = payload["models"]
    people = payload["volunteers"]

    header = ["id", "name", "source_url", "source_type", "section"]
    for m in models:
        s = short(m)
        header += [f"{s}_name", f"{s}_categories", f"{s}_skills"]
    header.append("gdrive_headings")

    rows = []
    for p in people:
        ex = p.get("extractions", {})
        row = {
            "id": p["id"],
            "name": p.get("name") or best_name(ex, models),
            "source_url": p.get("url") or "",
            "source_type": p.get("source_type") or "",
            "section": p.get("section") or "",
        }
        for m in models:
            s = short(m)
            e = ex.get(m)
            row[f"{s}_name"] = (e or {}).get("name") or ""
            row[f"{s}_categories"] = fmt_categories(e)
            row[f"{s}_skills"] = fmt_skills(e)
        row["gdrive_headings"] = "; ".join(p.get("gdrive_headings") or [])
        rows.append(row)

    rows.sort(key=lambda r: (r["section"], r["name"].lower()))

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows x {len(header)} cols -> {OUT.relative_to(ROOT)}")
    print(f"Models compared: {models}")


if __name__ == "__main__":
    main()
