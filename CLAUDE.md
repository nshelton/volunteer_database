# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A skills database of SIGGRAPH volunteers. The database is a **Google Sheet**; a **vanilla-JS frontend** (`web/`) served by a small Flask app (`cloudrun/`) on Cloud Run reads it in the browser and lets people browse, search, and matchmake. A **local data pipeline** (`src/`) extracts structured skills from resumes/portfolios with a local LLM. There are no tests and no linter.

**No personal data goes in git.** `data/` and `volunteer_list.txt` are gitignored local working files, and the site ships with no volunteer data at all.

## Commands

```bash
# venv (Python 3, playwright needed only for scraping)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# pipeline (each stage is cached/idempotent — re-runs only do new work)
.venv/bin/python src/parse_list.py                 # volunteer_list.txt -> data/records.json
.venv/bin/python src/ingest.py                     # fetch resume text -> data/raw/
.venv/bin/python src/ingest_report.py              # status overview
PYTHONPATH=src .venv/bin/python src/extract.py     # local LLM -> data/extracted/, data/volunteers.json
PYTHONPATH=src .venv/bin/python src/build_web.py   # -> web/data/taxonomy.json

# preview locally: needs web/auth-config.json (gitignored), and http://localhost:8000
# listed as an authorized JavaScript origin on the OAuth client
#   {"client_id": "<GOOGLE_CLIENT_ID>", "sheet_id": "<form sheet>", "db_sheet_id": "<database sheet>"}
cd web && python -m http.server 8000

# deploy (rebuilds the taxonomy, bundles web/ -> cloudrun/web/, gcloud run deploy)
bash cloudrun/deploy_run.sh

# change the email allowlist / OAuth client
bash cloudrun/set_auth.sh <GOOGLE_CLIENT_ID> "a@gmail.com,b@gmail.com"
```

`extract.py` talks to a local LLM over an OpenAI-compatible API, selected by `LLM_BACKEND`: `lmstudio` (default) or `ollama`. Full re-extraction across both models: `bash scripts/reextract_lmstudio.sh`. Extraction runs on a machine with the models loaded — see `docs/run-gdrive-extraction.md`.

## Architecture

**The Google Sheet is the database**, joined across tabs by `id`:
- `People` — hand-edited, one row per person: `id, name, email, status, group, source_url, source_type, notes`. `status` (`applied` / `confirmed` / `declined` / `alumni`) is what separates real volunteers from people who have only applied.
- `Profiles` — written by tooling, one row per `id`: headline, summary, and `;`-separated `skills, tools, roles, education, themes`, plus `openalex_url, orcid, works_count`.
- `Categories` — written by tooling, one row per person per category: `id, category, level, evidence`.
- `Publications` — written by tooling: `id, title, venue, year, doi, citations`.

`web/js/data.js` reads all four tabs in one `values:batchGet` call and shapes them into the person records every view renders (`shapePeople`). Tooling must never write to `People`, so a re-extraction can't overwrite a hand edit. Nothing syncs the pipeline's output into the sheet yet.

**Local pipeline:** `volunteer_list.txt` → `records.json` → `data/raw/<id>` → `data/extracted/<model>/<id>.json` → `data/volunteers.json`, all untracked. `data/volunteers.json` has exactly ONE writer — `src/aggregate.py`, a pure function of `data/extracted/`, `records.json`, and the gdrive/publications caches; every pipeline script re-aggregates when it finishes, so run order doesn't matter.

**`src/taxonomy.py` is the single source of truth** for the hybrid skill model: fixed SIGGRAPH-flavoured categories (with level + evidence per person) plus free-form skills/tools tags. Edit the category dict there and the extraction prompt, build, and UI all follow.

**Frontend** (`web/`): one framework-free page built from native ES modules in `web/js/` — no build step. Shared mutable state is one plain object `S` in `state.js`; dependencies run one direction (util → state → data → card → modes → main), each mode (browse, match, map, skills, table, signups) is its own module, and `main.js` is boot + controls + the `render()` dispatcher. Profile embeddings are computed in the browser after load (`semantic.js`, transformers.js all-MiniLM-L6-v2, cached in `localStorage` by a hash of each profile's text) with the same model that embeds the query, so query·profile cosine is a dot product; the map is a UMAP of those vectors, also computed in the browser. `web/` is canonical; `cloudrun/web/` is an untracked deploy-time copy made by `deploy_run.sh` — never edit it.

**Auth** has two grants (`web/auth.js`). A Google ID token identifies the user; the server checks its verified email against `ALLOWED_EMAILS` before serving `/data/*` and `/api/*` (skipped on localhost). An OAuth access token (`spreadsheets.readonly`) then lets the browser read the sheets as that user, so **the database sheet's sharing settings decide who sees volunteer data** — adding a collaborator means the allowlist *and* sharing the sheet. `/auth-config.json` hands the frontend `GOOGLE_CLIENT_ID`, `SHEET_ID` (form responses) and `DB_SHEET_ID` (the database).

**Signup state** lives in a GCS bucket (`setup_bucket.sh`), not the image:
- `signups.json` — mirror of the Google Form responses sheet. Nick does not own the sheet, so there is **no service-account access**: the browser reads it with the signed-in user's own OAuth token and POSTs the rows to `/api/signups`.
- `links.json` — the hand-curated join `{email -> volunteer_id}`. A signup whose email matches a `People` row's `email` joins automatically; for the rest the mapping is made by hand in the UI and written under a GCS generation precondition (`write_links`) so concurrent edits retry instead of clobbering.

The only other file under `/data/` is `taxonomy.json`, a build artifact with no personal data, baked into the image.
