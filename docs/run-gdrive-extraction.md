# Running the extraction locally (LM Studio or Ollama)

Goal: give every volunteer — including the 26 gdrive people — the **same
structured extractions** (categories/levels/skills/tools/roles) by running their
text through a local LLM with `extract.py`'s prompt + 23-category schema. After
this, gdrive people are first-class: filterable by category, colored in the Map,
rankable in Matchmake, and embedded with real skills.

The pipeline talks to a local LLM over an **OpenAI-compatible** API. Two backends
are supported, selected by the `LLM_BACKEND` env var:

- **`lmstudio`** (default) — [LM Studio](https://lmstudio.ai)'s server, structured
  output via `response_format=json_schema`.
- **`ollama`** — the original Ollama `/api/chat` + `format` path.

## 1. Get the code + data

```bash
git clone https://github.com/nshelton/volunteer_database.git   # or: git pull
cd siggraph-vdc
git checkout feature/gdrive-summaries
```

The gdrive prose is committed in `data/gdrive_headings.json` (and the source
`data/gdrive/*.docx`), so no docx parsing is needed to re-run inference.

## 2. Environment

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install httpx        # the only dep the LLM steps need
```

### LM Studio (default)

1. Install LM Studio and download two models (or pick your own — see overrides):
   - `qwen/qwen3-30b-a3b-2507`  (Qwen, MoE, fast)
   - `google/gemma-4-31b`        (Gemma, dense, higher quality)
2. Start the server and **load each model with a large context** (the prompt can
   reach ~7k tokens; the default 4k will truncate it):

```bash
export PATH="$HOME/.lmstudio/bin:$PATH"
lms server start
lms load qwen/qwen3-30b-a3b-2507 --context-length 16384 --gpu max -y
lms load google/gemma-4-31b      --context-length 16384 --gpu max -y
lms ps   # confirm both are loaded at 16384 context
```

LM Studio serves the OpenAI API at `http://127.0.0.1:1234/v1` (the default).

### Ollama (alternative)

```bash
brew install ollama && ollama serve &
ollama pull qwen2.5:7b-instruct && ollama pull gemma2:9b
export LLM_BACKEND=ollama
```

### Env overrides (either backend)

| var | default | meaning |
|---|---|---|
| `LLM_BACKEND` | `lmstudio` | `lmstudio`/`openai` or `ollama` |
| `LLM_BASE_URL` | `http://127.0.0.1:1234/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | `qwen/qwen3-30b-a3b-2507` | default model if `--model` omitted |

To poke at a different local model, just `lms load` it and pass its id with
`--model`, e.g. `--model qwen/qwen3-coder-30b`. The on-disk output dir and the
model key in `volunteers.json` are slugified from that id.

## 3. Poke at gdrive inference

Run a single gdrive person end-to-end (writes
`data/extracted/<model>/<id>.json`, prints the categories):

```bash
PYTHONPATH=src .venv/bin/python src/extract_gdrive.py --only <id> --force
```

Run all 26 gdrive people for one model:

```bash
PYTHONPATH=src .venv/bin/python src/extract_gdrive.py --model qwen/qwen3-30b-a3b-2507 --force
PYTHONPATH=src .venv/bin/python src/extract_gdrive.py --model google/gemma-4-31b      --force
```

`extract_gdrive.py` reuses `extract.py`'s system prompt, user template, and JSON
schema verbatim, and patches `extractions[<model>]` into `data/volunteers.json`
**in place** (preserving the gdrive headings/summary + publications already
there). It is idempotent — re-running skips cached people unless `--force`.

## 4. Full re-extraction of EVERYONE (scraped + gdrive)

`scripts/reextract_lmstudio.sh` runs the whole dataset in the correct order
(scraped qwen → scraped gemma → restore gdrive headings/publications → gdrive
qwen → gdrive gemma → build web). On macOS, wrap it in `caffeinate` so the box
doesn't sleep mid-run, and run it detached:

```bash
nohup caffeinate -dis bash scripts/reextract_lmstudio.sh > /tmp/reextract.log 2>&1 &
tail -f /tmp/reextract.log        # progress (note: per-record lines are block-buffered)
```

It takes ~60–90 min for both 30B models on an Apple-Silicon Mac.

> **Only run one extraction at a time.** Two concurrent runs write the same files
> and corrupt the dataset. If you kill a run, kill **both** `extract.py` *and*
> `extract_gdrive.py` (and the `caffeinate`/script wrapper):
> `pkill -9 -f "extract.py|extract_gdrive|reextract_lmstudio|caffeinate -dis"`.

## 5. Rebuild the taxonomy

```bash
PYTHONPATH=src .venv/bin/python src/build_web.py          # taxonomy -> web/data/
```

## 6. Serve locally

```bash
python3 -m http.server 8000 --bind 0.0.0.0 --directory web
# open http://<this-machine>.local:8000/  (or /v2.html)
```

## Notes

- **Don't** run plain `src/extract.py` (the aggregator) after a gdrive run — it
  rebuilds `volunteers.json` from `data/extracted/*` + `records.json` and would
  drop the gdrive headings/summary + publications. `extract_gdrive.py` patches in
  place on purpose. If you ever do re-aggregate, re-run `ingest_gdrive.py` then
  `ingest_publications.py` (or restore from a snapshot) to put those fields back.
- The schema caps each array (`maxItems`) so a model can't run away emitting list
  items on long/noisy resumes; see `build_schema()` in `src/extract.py`.
- Model keys in `web/v2.js` (`MODEL_ORDER`) and `src/embed_profiles.mjs` (`ORDER`)
  must match the models you extract with, so the UI/embeddings pick a primary.
