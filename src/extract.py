"""Skill extraction: raw resume text -> structured volunteer record.

Runs each cached raw text through a local LLM and forces a strict JSON schema
(hybrid taxonomy: fixed categories + free-form keyword tags). Backend selected
by LLM_BACKEND: "lmstudio" (default, OpenAI-compatible server) or "ollama".

Outputs:
    data/extracted/<model>/<id>.json  -- one structured record per person
    data/volunteers.json              -- rebuilt at the end via aggregate.py

Idempotent: skips records already extracted unless --force / --only.

Prereqs: LM Studio serving with the model loaded (see README "Local LLM"),
or `ollama serve` with LLM_BACKEND=ollama.

Usage:
    python src/extract.py
    python src/extract.py --force
    python src/extract.py --only jdoe
    python src/extract.py --model qwen/qwen3-30b-a3b-2507
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import httpx

from aggregate import aggregate
from taxonomy import CATEGORY_KEYS, LEVELS, SENIORITY, prompt_category_block

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "data" / "records.json"
RAW_DIR = ROOT / "data" / "raw"
EXTRACT_ROOT = ROOT / "data" / "extracted"   # one subdir per model


def model_slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def model_dir(model: str) -> Path:
    return EXTRACT_ROOT / model_slug(model)

# --- Local LLM backend -------------------------------------------------------
# Two backends are supported, selected by LLM_BACKEND:
#   "lmstudio"/"openai" (default) -> LM Studio's OpenAI-compatible server,
#                                    structured output via response_format=json_schema.
#   "ollama"                       -> the original Ollama /api/chat + `format` path.
# Override the endpoint/model with LLM_BASE_URL / LLM_MODEL (OLLAMA_* still honored).
LLM_BACKEND = os.environ.get("LLM_BACKEND", "lmstudio").lower()
OLLAMA_URL = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
OPENAI_BASE_URL = os.environ.get(
    "LLM_BASE_URL", os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:1234/v1")
).rstrip("/")
DEFAULT_MODEL = os.environ.get(
    "LLM_MODEL", os.environ.get("OLLAMA_MODEL", "qwen/qwen3-30b-a3b-2507")
)

# Statuses whose raw text is worth extracting from.
EXTRACTABLE = {"ok", "thin"}

# Deterministic backstop: raw text dominated by these = a website-builder/login
# stub, not a real profile. Independent of the LLM's judgment.
JUNK_SIGNATURES = (
    "create a free website with framer",
    "make your own website",
    "this site was created with",
    "powered by squarespace",
    "create your website today",
    "wix.com",
    "sign in to continue",
    "enable javascript to run this app",
)


def looks_like_nonprofile(raw: str) -> bool:
    low = raw.lower()
    return len(raw) < 700 and any(sig in low for sig in JUNK_SIGNATURES)


def looks_like_real_name(name: str) -> bool:
    """Reject URL slugs, handles, filenames, hashes; accept real human names."""
    n = (name or "").strip()
    if not n:
        return False
    if re.search(r"\d", n):
        return False
    if re.search(r"(file-?d|files-?ugd|http|www|\.com|_|/)", n, re.I):
        return False
    words = n.split()
    if len(words) >= 2:  # "Jane Doe"
        return True
    tok = words[0]  # single token: only if a normal capitalized word, not a handle
    return len(tok) <= 12 and tok[:1].isupper() and tok.isalpha()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _is_slug_handle(name: str, slug: str) -> bool:
    """A single-token name that just echoes the URL slug is a handle, not a real
    name (e.g. "Jdoe" from /jdoe). A multi-word name that happens to match
    the slug (e.g. "Jane Doe" vs janedoe) is a real name."""
    return " " not in (name or "").strip() and _norm(name) == _norm(slug)


def resolve_name(model_name: str, name_hint: str, slug: str) -> str:
    """Prefer the model's extracted name; fall back to a plausible hint; else Unknown."""
    if looks_like_real_name(model_name) and not _is_slug_handle(model_name, slug):
        return model_name.strip()
    if looks_like_real_name(name_hint) and not _is_slug_handle(name_hint, slug):
        return name_hint.strip()
    return "Unknown"

SYSTEM = (
    "You are an expert technical recruiter for SIGGRAPH, the premier computer "
    "graphics conference. You read a person's resume / CV / portfolio / profile "
    "text and extract a precise, structured skills profile. Only use information "
    "supported by the text. Do not invent skills, employers, or schools. If the "
    "text is sparse, return what little is supported and leave other fields empty. "
    "Always respond with a single JSON object matching the requested schema."
)

USER_TEMPLATE = """Extract a structured volunteer profile from the text below.

Assess data quality honestly, but ALWAYS extract whatever is supported:
- `is_personal_profile`: true if the text is an individual's resume / CV / portfolio
  / professional profile. A name with a job title, a LinkedIn header, or a list of
  skills all COUNT — be generous; almost all inputs are real profiles. Set false
  ONLY for website-builder chrome ("Create a free website with Framer/Wix"), a
  sign-in / login / error page, or an empty stub with no professional content.
- `data_quality`: "not_a_profile" only for those junk cases; "sparse" for a real
  but very thin profile; "good" otherwise.
- ALWAYS populate categories/skills/tools with everything the text supports. Do NOT
  withhold skills for a real profile. Leave them empty ONLY for a genuine junk page.
- NEVER treat a website-builder's name ("Framer", "Wix", "Squarespace", "WordPress")
  as a skill — those build the site; they are not the person's skills.

If it IS a real profile, assign the person to the relevant SIGGRAPH skill
categories (only those with real evidence in the text). Available categories:
{categories}

Rules:
- `name`: the person's REAL full name exactly as written in the visible text
  (usually a heading or a contact/description block, e.g. "Jane Doe", "Alex Rivera").
  Do NOT use URL slugs, handles, usernames, or file names (e.g. "jdoe42",
  "file-d-1rfk...", "doeray"). If the text has no real human name, use "" (empty).
- `headline`: a concise professional headline (e.g. "PhD researcher in neural
  rendering" or "Senior VFX technical director"). Synthesize one from the text
  even if not stated verbatim. Never leave empty if the text has any signal.
- `summary`: 1-2 sentence plain-language summary of who they are and what they do.
- `categories`: include EVERY category genuinely supported by the text -- map the
  skills, tools, projects, and publications to categories (e.g. "neural networks"
  and "3D reconstruction" imply machine_learning and computer_vision). For each,
  give a `level` (familiar/proficient/expert) and a short `evidence` quote/paraphrase.
- `skills`: free-form specific keywords (e.g. "path tracing", "Houdini", "PyTorch",
  "rigging", "WebGL"). Tools/software go in `tools`.
- `roles`: job titles / positions held.
- `seniority`: one of {seniority}.
- Don't invent facts, but DO infer category membership from concrete evidence.

--- PROFILE TEXT (source: {source}) ---
{text}
--- END TEXT ---
"""


def build_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "is_personal_profile": {"type": "boolean"},
            "data_quality": {"type": "string", "enum": ["good", "sparse", "not_a_profile"]},
            "name": {"type": "string"},
            "headline": {"type": "string"},
            "summary": {"type": "string"},
            "location": {"type": "string"},
            "seniority": {"type": "string", "enum": SENIORITY + [""]},
            "years_experience": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "categories": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": CATEGORY_KEYS},
                        "level": {"type": "string", "enum": LEVELS},
                        "evidence": {"type": "string"},
                    },
                    "required": ["category", "level"],
                },
            },
            # maxItems caps bound generation: some local models otherwise run away
            # emitting array items on long/noisy resumes until they hit the context
            # limit (slow + bloated). Caps are well above the old pipeline's p90.
            "skills": {"type": "array", "maxItems": 40, "items": {"type": "string"}},
            "tools": {"type": "array", "maxItems": 30, "items": {"type": "string"}},
            "roles": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
            "education": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
        },
        "required": ["is_personal_profile", "data_quality", "name", "categories", "skills", "tools"],
    }


def _build_user(text: str, source: str) -> str:
    return USER_TEMPLATE.format(
        categories=prompt_category_block(),
        seniority="/".join(SENIORITY),
        source=source,
        text=text[:16000],  # plenty for a resume; guards pathological pages
    )


def _call_ollama(model: str, user: str, schema: dict) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": schema,  # Ollama: raw JSON schema forces structured output
        "options": {"temperature": 0, "num_ctx": 8192},
    }
    with httpx.Client(timeout=600.0) as client:
        resp = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


def _call_openai(model: str, user: str, schema: dict) -> str:
    """LM Studio / any OpenAI-compatible server. Structured output via
    response_format=json_schema (constrained decoding). The serving context
    length is set at model-load time (>= ~8k needed for the truncated prompt)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "volunteer_profile", "schema": schema, "strict": True},
        },
    }
    with httpx.Client(timeout=600.0) as client:
        resp = client.post(f"{OPENAI_BASE_URL}/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def call_model(model: str, text: str, source: str, schema: dict) -> dict:
    """Run one extraction against the configured local LLM backend."""
    user = _build_user(text, source)
    raw = _call_ollama(model, user, schema) if LLM_BACKEND == "ollama" \
        else _call_openai(model, user, schema)
    if not (raw or "").strip():
        raise RuntimeError("empty completion (model returned no content)")
    return json.loads(raw)


def load_meta(rec_id: str) -> dict | None:
    p = RAW_DIR / f"{rec_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", help="single record id")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    out_dir = model_dir(args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = {r["id"]: r for r in json.loads(RECORDS.read_text())}
    schema = build_schema()

    targets = []
    for rec_id, rec in records.items():
        if args.only and rec_id != args.only:
            continue
        meta = load_meta(rec_id)
        if not meta or meta["status"] not in EXTRACTABLE:
            continue
        if (RAW_DIR / f"{rec_id}.txt").read_text().strip() == "":
            continue
        out = out_dir / f"{rec_id}.json"
        if out.exists() and not args.force:
            continue
        targets.append(rec_id)

    if not targets:
        print("Nothing to extract (all done, or use --force). Aggregating...")
    else:
        print(f"Extracting {len(targets)} profile(s) with {args.model}...\n")

    for i, rec_id in enumerate(targets, 1):
        rec = records[rec_id]
        text = (RAW_DIR / f"{rec_id}.txt").read_text()
        try:
            data = call_model(args.model, text, rec["source_type"], schema)
        except Exception as e:  # noqa: BLE001
            print(f"[{i:2}/{len(targets)}] ERR  {rec_id}: {type(e).__name__}: {e}")
            continue
        # Decide non-profile only when corroborated: deterministic builder/login
        # junk, OR the model flags it AND the text is too thin to be a real
        # profile. This protects substantial profiles the model misjudges.
        deterministic = looks_like_nonprofile(text)
        model_says_no = (not data.get("is_personal_profile", True)) or \
            data.get("data_quality") == "not_a_profile"
        nonprofile = deterministic or (model_says_no and len(text) < 500)

        if nonprofile:
            data["is_personal_profile"] = False
            data["data_quality"] = "not_a_profile"
            for k in ("categories", "skills", "tools", "roles"):
                data[k] = []
            data["name"] = "Unknown"
        else:
            data["is_personal_profile"] = True
            data["name"] = resolve_name(data.get("name", ""), rec.get("name_hint") or "", rec_id)
            if not data.get("categories"):
                data["data_quality"] = "sparse"
            elif data.get("data_quality") == "not_a_profile":
                data["data_quality"] = "good"

        data["id"] = rec_id
        data["model"] = args.model
        (out_dir / f"{rec_id}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if data["data_quality"] == "not_a_profile":
            print(f"[{i:2}/{len(targets)}] SKIP {data['name'][:24]:24} -> not a profile (insufficient)")
        else:
            cats = ", ".join(c["category"] for c in data.get("categories", [])) or "(none)"
            print(f"[{i:2}/{len(targets)}] OK   {data['name'][:24]:24} -> {cats[:60]}")

    aggregate()


if __name__ == "__main__":
    main()
