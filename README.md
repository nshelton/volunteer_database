# SIGGRAPH Volunteer Database

A volunteer management tool for SIGGRAPH: one place to see who has applied, who
is a confirmed volunteer, and what each person is good at, with a web UI to
**browse, search, and matchmake** people to committee needs.

The database is a **Google Sheet**. This repository holds code only: **no
volunteer data is committed here**, and none ships with the site.

## How it fits together

```
Google Sheet  (the database: People, Profiles, Categories, Publications)
   │   read in the browser with the signed-in user's own Google access
   ▼
web/        vanilla-JS frontend: browse / matchmake / map / skills graph / table / signups
cloudrun/   small Flask app on Cloud Run: serves the page, checks the allowlist,
            and keeps the form-signup state in a storage bucket

src/        local pipeline: resumes -> structured skills with a local LLM
            (works on gitignored files under data/; nothing writes its output
            into the Sheet yet)
```

## The Sheet

Tabs are joined by `id`. Edit people by hand in `People`; the other three tabs
are for tooling, and tooling must never write to `People`, so a re-extraction
cannot overwrite a hand edit.

| Tab | Written by | Columns |
|---|---|---|
| `People` | People, by hand | `id, name, email, status, group, source_url, source_type, notes` |
| `Profiles` | Tooling | `id, model, data_quality, headline, summary, location, seniority, years_experience, skills, tools, roles, education, themes, openalex_url, orcid, works_count` |
| `Categories` | Tooling | `id, category, level, evidence` (one row per person per category) |
| `Publications` | Tooling | `id, title, venue, year, doi, citations` |

- `status` is `applied`, `confirmed`, `declined` or `alumni`. It is what
  separates real volunteers from people who have only applied; the site greys
  out `applied` people and can filter to them.
- `id` is the key. Never change or reuse one.
- List cells (`skills`, `tools`, `roles`, `education`, `themes`) are separated
  by semicolons.
- A row's `email` joins that person to their form signup automatically.

Edits show up on the site at the next page load. There is no rebuild or
redeploy for data changes.

## Access

Seeing volunteer data takes two things:

1. Your Google email is on the site's allowlist (`ALLOWED_EMAILS`).
2. The database Sheet is shared with you (view access is enough).

On sign-in the site asks for a second grant, read access to Google Sheets, and
then reads the Sheet as you. So the Sheet's sharing settings are the real gate
on the data.

```bash
# Set the allowlist (and OAuth client). Always pass the full list:
bash cloudrun/set_auth.sh <GOOGLE_CLIENT_ID> "a@gmail.com,b@gmail.com"
```

While the OAuth consent screen is in "testing" mode, allowed users must also be
listed there as test users (Cloud Console > APIs & Services > OAuth consent
screen).

## Run the site locally

There is no build step. The page still signs in to Google and reads the real
Sheet, so it needs the OAuth client:

1. Add `http://localhost:8000` as an **Authorized JavaScript origin** on the
   OAuth client (Cloud Console > APIs & Services > Credentials).
2. Create `web/auth-config.json` (gitignored):
   ```json
   {"client_id": "<GOOGLE_CLIENT_ID>", "sheet_id": "<form responses sheet id>", "db_sheet_id": "<database sheet id>"}
   ```
3. Serve it:
   ```bash
   cd web && python3 -m http.server 8000      # http://localhost:8000
   ```

Locally the allowlist is skipped, and the signup sync and linking are
unavailable because they need the Cloud Run backend.

## Deploy

Hosted on **Cloud Run** (project `siggraph-vdc`, service `siggraph-vdc`, region
`us-central1`).

```bash
bash cloudrun/deploy_run.sh      # rebuilds the taxonomy, bundles web/, deploys
```

- Live: https://siggraph-vdc-222919468594.us-central1.run.app
- Environment variables are kept across redeploys: `GOOGLE_CLIENT_ID`,
  `ALLOWED_EMAILS`, `GCS_BUCKET`, `SHEET_ID` (form responses) and `DB_SHEET_ID`
  (the database Sheet).
- The OAuth client is type "Web application". Every address the site is opened
  from must be one of its Authorized JavaScript origins, or Google refuses the
  sign-in with `origin_mismatch`. Cloud Run gives the service two URLs; register
  the ones you use.
- `cloudrun/setup_bucket.sh` is the one-time setup for the bucket that holds
  the signup state.

`web/` is the source for the frontend. `cloudrun/web/` is an untracked copy
made by the deploy script; never edit it.

### What the server stores

Only the form-signup state, in a storage bucket: `signups.json`, a mirror of the
Google Form responses pushed when someone clicks Sync on the site, and
`links.json`, hand-made joins between a signup email and a person for signups
whose email is not yet in the Sheet.

## Skill model

Hybrid: a fixed set of SIGGRAPH-relevant **categories** (see `src/taxonomy.py`)
for clean matchmaking, plus free-form **skills** and **tools** tags per person
for nuance. Each category assignment carries a `level`
(familiar / proficient / expert) and an `evidence` snippet.

`src/taxonomy.py` is the single source for the categories: the extraction
prompt and the UI both follow it.

Semantic search, "find similar" and the map use profile embeddings computed in
the browser after the page loads (all-MiniLM-L6-v2 via transformers.js), cached
per browser. The first load downloads the model, about 25 MB.

## Extraction pipeline (local)

Turns a list of resume / portfolio / LinkedIn URLs into structured skills using
a local LLM. Everything it reads and writes lives under `data/` and
`volunteer_list.txt`, which are gitignored because they are personal data.

```
volunteer_list.txt
   │  parse_list.py          -> data/records.json                  (classify each URL)
   │  ingest.py              -> data/raw/<id>                      (fetch resume text)
   │  scrape_linkedin.py     -> data/raw/...                       (authed LinkedIn fetch)
   │  extract.py (local LLM) -> data/extracted/<model>/<id>.json
   ▼                            data/volunteers.json               (aggregated)
```

Each stage is cached and idempotent. `data/volunteers.json` has one writer,
`src/aggregate.py`, and every pipeline script re-aggregates when it finishes.

**There is no script yet that writes this output into the Sheet.** The Sheet's
current contents were imported once by hand.

Setup:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium     # only for scraping
```

LM Studio is the default backend (`LLM_BACKEND=lmstudio`), serving its
OpenAI-compatible API on `127.0.0.1:1234`:

```bash
lms load qwen/qwen3-30b-a3b-2507 --context-length 16384 --gpu max -y
lms load google/gemma-4-31b      --context-length 16384 --gpu max -y
```

Ollama also works: set `LLM_BACKEND=ollama` (endpoint and model via
`OLLAMA_HOST_URL` / `OLLAMA_MODEL`).

Run:

```bash
.venv/bin/python src/parse_list.py
.venv/bin/python src/ingest.py
.venv/bin/python src/ingest_report.py               # status overview

# LinkedIn: manual login once, then a slow paced fetch (needs a display)
.venv/bin/python src/scrape_linkedin.py login
.venv/bin/python src/scrape_linkedin.py scrape --limit 10

PYTHONPATH=src .venv/bin/python src/extract.py
bash scripts/reextract_lmstudio.sh                  # full two-model re-extraction
```

`src/ingest_publications.py` looks people up on OpenAlex and needs
`OPENALEX_MAILTO` set to your email. `src/ingest_gdrive.py` reads
`data/gdrive_aliases.json`, a map from document name to existing `id`. See
`docs/run-gdrive-extraction.md` for a full extraction walkthrough.

## Notes and limits

- **LinkedIn** can't be fetched without an authenticated session; the scraper
  uses your own login and is paced slowly. This is against LinkedIn's terms of
  service: use a secondary account, small scale, internal use only.
- Some sources are dead ends for automation (a non-shared Drive file, a
  "download CV" button, a single-page resume app) and need the volunteer to
  re-share.
- There are no tests and no linter.
