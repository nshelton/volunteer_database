# SIGGRAPH Volunteer Skills Database

Builds a searchable skills database of SIGGRAPH volunteers by extracting skills
from their resumes / portfolios / LinkedIn profiles with a **local LLM**, and
serves a web UI to **browse, search, and matchmake** volunteers to committee
needs.

## Pipeline

```
volunteer_list.txt
   │  parse_list.py        -> data/records.json        (classify each URL)
   │  ingest.py            -> data/raw/<id>.{txt,json}  (fetch resume text)
   │  scrape_linkedin.py   -> data/raw/...              (authed LinkedIn fetch)
   │  extract.py (local LLM) -> data/extracted/<model>/<id>.json  (hybrid skill taxonomy)
   │                            data/volunteers.json              (aggregated)
   ▼
(local working files only; `data/` is gitignored and holds personal data)

Google Sheet (the volunteer database)
   ▼  read in the browser with the signed-in user's Google access
web/  (single frontend: browse / matchmake / map / skills graph)  ->  Cloud Run
```

Each stage is **cached, idempotent, and order-free** — re-running only does
new/changed work. `data/volunteers.json` has exactly one writer,
`src/aggregate.py`, a pure function of `data/extracted/`, `data/records.json`,
and the gdrive/publications caches; every pipeline script re-aggregates when it
finishes, and you can also run `python3 src/aggregate.py` directly.
`scripts/reextract_lmstudio.sh` runs the full two-model re-extraction.

## Setup

Clone the repo (it is private):

```bash
git clone https://github.com/nshelton/siggraph-vdc.git
cd siggraph-vdc
```

No volunteer data is in the repo: `data/` and `volunteer_list.txt` are gitignored
working files for the local pipeline, and the site reads the volunteer database
from a Google Sheet. The `.venv` is not
tracked — recreate the venv locally, and only re-run the LinkedIn login if you
need to fetch new profiles.

Create the environment:

```bash
python3 -m venv .venv
.venv/bin/python -m ensurepip --upgrade
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Local LLM — LM Studio is the default backend (`LLM_BACKEND=lmstudio`), serving
its OpenAI-compatible API on `127.0.0.1:1234`. Install it (https://lmstudio.ai),
then load the extraction models:

```bash
lms load qwen/qwen3-30b-a3b-2507 --context-length 16384 --gpu max -y
lms load google/gemma-4-31b      --context-length 16384 --gpu max -y
```

Ollama still works as an alternative: `ollama serve`, pull a model, and set
`LLM_BACKEND=ollama` (endpoint/model via `OLLAMA_HOST_URL` / `OLLAMA_MODEL`).

## Run

```bash
# 1. parse the source list
.venv/bin/python src/parse_list.py

# 2. fetch the accessible resumes (Drive / web / GitHub / PDF)
.venv/bin/python src/ingest.py
.venv/bin/python src/ingest_report.py        # status overview

# 3. LinkedIn (manual login once, then slow paced fetch) -- needs a display
.venv/bin/python src/scrape_linkedin.py login
.venv/bin/python src/scrape_linkedin.py scrape --limit 10

# 4. extract structured skills with the local LLM (LM Studio; see above)
PYTHONPATH=src .venv/bin/python src/extract.py
# full two-model re-extraction (qwen + gemma, gdrive, publications, build):
bash scripts/reextract_lmstudio.sh

# 5. build the web payload and preview
PYTHONPATH=src .venv/bin/python src/build_web.py
cd web && python -m http.server 8000      # http://127.0.0.1:8000

# 6. deploy to Cloud Run (rebuilds web/data, bundles web/, deploys)
bash cloudrun/deploy_run.sh
```

## Deployment

Hosted on **Cloud Run** (project `siggraph-vdc`, service `siggraph-vdc`,
region `us-central1`) behind **Google Sign-In**. The Flask app (`cloudrun/`)
serves the UI shell publicly but releases the volunteer data under `/data/*`
ONLY to a request carrying a valid Google ID token whose email is on the
allowlist — verification is server-side, so the data is genuinely private.

- Live: https://siggraph-vdc-222919468594.us-central1.run.app
- Auth: Google Sign-In popup; access limited to `ALLOWED_EMAILS`.
- Redeploy after data changes: `bash cloudrun/deploy_run.sh`
  (env vars are preserved across redeploys).

Access control:
```bash
# Add/remove people (or change the OAuth client). Re-run with the full list:
bash cloudrun/set_auth.sh <GOOGLE_CLIENT_ID> "a@gmail.com,b@gmail.com,c@gmail.com"
```
The allowed users must also be **test users** on the OAuth consent screen while
it is in "testing" mode (Cloud Console → APIs & Services → OAuth consent screen).

OAuth client: type "Web application", Authorized JavaScript origin =
the Cloud Run URL above. The client ID is not a secret (used by the frontend).

`web/` is the single source of truth for the frontend (the former v2 page,
now canonical, with v1's force-directed skills graph folded in as the Skills
mode). `cloudrun/web/` is a deploy-time bundle created by `deploy_run.sh`
(not tracked in git). The old `gs://siggraph-vdc-site` bucket deployment
(`src/deploy.sh`) has been removed.

## Skill model

Hybrid: a fixed set of SIGGRAPH-relevant **categories** (see `src/taxonomy.py`)
for clean matchmaking, plus free-form **skills** / **tools** keyword tags per
person for nuance. Each category assignment carries a `level`
(familiar/proficient/expert) and an `evidence` snippet.

## Notes / limits

- **LinkedIn** can't be fetched without an authenticated session; the scraper
  uses your own login and is paced slowly. This is against LinkedIn's ToS — use
  a secondary account, small scale, internal use only.
- A few sources are dead ends for automation (a non-shared Drive file, a Framer
  "download CV" link, a resume.io SPA) and need the volunteer to paste / re-share.
- Model choice is configurable (`--model`); quality to be evaluated later.
```
