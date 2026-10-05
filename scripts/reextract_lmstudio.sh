#!/usr/bin/env bash
# Full re-extraction of every volunteer (scraped + gdrive) through the local
# LM Studio models. volunteers.json is rebuilt by aggregate.py at the end of
# each step, so the steps are order-free — this is just the canonical sequence.
#
# Prereqs: LM Studio server running with BOTH models loaded at >=8k context:
#   lms load qwen/qwen3-30b-a3b-2507 --context-length 16384 --gpu max -y
#   lms load google/gemma-4-31b      --context-length 16384 --gpu max -y
#
# Run:  bash scripts/reextract_lmstudio.sh
set -uo pipefail
cd "$(dirname "$0")/.."

export LLM_BACKEND=lmstudio
PY=.venv/bin/python
QWEN="qwen/qwen3-30b-a3b-2507"
GEMMA="google/gemma-4-31b"
qslug="qwen-qwen3-30b-a3b-2507"
gslug="google-gemma-4-31b"

step() { echo; echo "===== $(date '+%H:%M:%S')  $* ====="; }
die()  { echo "ABORT: $*" >&2; exit 1; }
count(){ ls "data/extracted/$1"/*.json 2>/dev/null | wc -l | tr -d ' '; }

# 1. Scraped profiles — Qwen
step "1. extract.py scraped  --  $QWEN"
PYTHONPATH=src $PY src/extract.py --model "$QWEN" --force || die "extract.py qwen failed"
n=$(count "$qslug"); echo "  -> $n qwen extractions"; [ "$n" -ge 40 ] || die "too few qwen scraped ($n)"

# 2. Scraped profiles — Gemma
step "2. extract.py scraped  --  $GEMMA"
PYTHONPATH=src $PY src/extract.py --model "$GEMMA" --force || die "extract.py gemma failed"
n=$(count "$gslug"); echo "  -> $n gemma extractions"; [ "$n" -ge 40 ] || die "too few gemma scraped ($n)"

# 3. gdrive structured extractions — Qwen (overwrites scrape for the overlaps)
step "3. extract_gdrive.py  --  $QWEN"
PYTHONPATH=src $PY src/extract_gdrive.py --model "$QWEN" --force || die "extract_gdrive qwen failed"

# 4. gdrive structured extractions — Gemma
step "4. extract_gdrive.py  --  $GEMMA"
PYTHONPATH=src $PY src/extract_gdrive.py --model "$GEMMA" --force || die "extract_gdrive gemma failed"

# 5. Build the static web payload
step "5. build_web.py"
PYTHONPATH=src $PY src/build_web.py || die "build_web failed"

step "DONE — re-extraction complete"
