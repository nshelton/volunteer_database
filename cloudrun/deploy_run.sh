#!/usr/bin/env bash
# Rebuild the taxonomy and redeploy the Google-Sign-In-gated site to Cloud Run.
# Auth config (GOOGLE_CLIENT_ID, ALLOWED_EMAILS) is set once via set_auth.sh and
# preserved across these redeploys (no env flags here = keep existing env).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GCLOUD="$(command -v gcloud || echo "$HOME/google-cloud-sdk/bin/gcloud")"
PROJECT=siggraph-vdc
REGION=us-central1
SERVICE=siggraph-vdc

echo "==> Rebuilding web/data"
# build_web.py is stdlib-only, so the venv is a convenience here, not a requirement.
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
PYTHONPATH="$ROOT/src" "$PY" "$ROOT/src/build_web.py"

echo "==> Bundling web/ into cloudrun/web/"
rm -rf "$ROOT/cloudrun/web"
cp -r "$ROOT/web" "$ROOT/cloudrun/web"
rm -f "$ROOT/cloudrun/web/auth-config.json"   # local-preview config; the server answers this route

echo "==> Deploying to Cloud Run ($SERVICE / $REGION)"
"$GCLOUD" run deploy "$SERVICE" \
  --project="$PROJECT" --region="$REGION" \
  --source="$ROOT/cloudrun" \
  --allow-unauthenticated \
  --memory=256Mi --cpu=1 --max-instances=3 --quiet

URL="$($GCLOUD run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)')"
echo "==> Live (Google Sign-In): $URL"
