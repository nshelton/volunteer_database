"""Run the gdrive summary docs through the SAME extraction pipeline as the
scraped profiles, so gdrive people get identical structured extractions
(categories / levels / skills / tools / roles / ...) under the same model keys.

The only difference from scraped people is the source text: the teammate's
curated gdrive summary instead of LinkedIn/resume scrape. Reuses extract.py's
system prompt, user template, and JSON schema verbatim.

Prereq: the local LLM backend serving with the model loaded (LM Studio by
default, or Ollama via LLM_BACKEND=ollama — see README "Local LLM").

Writes, exactly like the scraped pipeline:
    data/extracted/<model>/<id>.json      -- one structured record per gdrive person
then rebuilds data/volunteers.json via aggregate.py.

Usage (run once per model, same as extract.py):
    PYTHONPATH=src python src/extract_gdrive.py --model qwen/qwen3-30b-a3b-2507
    PYTHONPATH=src python src/extract_gdrive.py --model google/gemma-4-31b
    PYTHONPATH=src python src/extract_gdrive.py --only "jdoe" --force

Then rebuild the payload + vectors:
    PYTHONPATH=src python src/build_web.py
    node src/embed_profiles.mjs && node src/project_embeddings.mjs
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import extract  # reuse SYSTEM/USER_TEMPLATE/build_schema/call_model/model_dir
from aggregate import aggregate

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "gdrive_headings.json"   # { id: {name, headings, summary} }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=extract.DEFAULT_MODEL)
    ap.add_argument("--only", help="single gdrive volunteer id")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cache = json.loads(CACHE.read_text())
    out_dir = extract.model_dir(args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = extract.build_schema()

    items = [(rid, g) for rid, g in cache.items() if not args.only or rid == args.only]
    print(f"Extracting {len(items)} gdrive profile(s) with {args.model}...\n")

    for i, (rid, g) in enumerate(items, 1):
        out = out_dir / f"{rid}.json"
        if out.exists() and not args.force:
            print(f"[{i:2}/{len(items)}] skip {g['name'][:24]:24} (cached)")
        else:
            text = g.get("summary") or ". ".join(g.get("headings", []))
            if not text.strip():
                print(f"[{i:2}/{len(items)}] skip {rid} (no text)")
                continue
            try:
                data = extract.call_model(args.model, text, "gdrive summary", schema)
            except Exception as e:  # noqa: BLE001
                print(f"[{i:2}/{len(items)}] ERR  {g['name']}: {type(e).__name__}: {e}")
                continue
            # Same post-processing as extract.py, but the gdrive name is authoritative.
            data["is_personal_profile"] = True
            data["name"] = g["name"]
            if not data.get("categories"):
                data["data_quality"] = "sparse"
            elif data.get("data_quality") == "not_a_profile":
                data["data_quality"] = "good"
            data["id"] = rid
            data["model"] = args.model
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            cats = ", ".join(c["category"] for c in data.get("categories", [])) or "(none)"
            print(f"[{i:2}/{len(items)}] OK   {g['name'][:24]:24} -> {cats[:54]}")

    print()
    aggregate()
    print("Next: build_web.py + re-embed.")


if __name__ == "__main__":
    main()
