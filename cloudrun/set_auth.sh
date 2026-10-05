#!/usr/bin/env bash
# Set (or change) the Google OAuth client ID and the allowed-email list on the
# Cloud Run service. Run once after creating the OAuth client, and again any
# time the allowlist changes.
#
#   bash cloudrun/set_auth.sh <GOOGLE_CLIENT_ID> email1,email2,...
#
set -euo pipefail

GCLOUD="$(command -v gcloud || echo "$HOME/google-cloud-sdk/bin/gcloud")"
REGION=us-central1
SERVICE=siggraph-vdc

CLIENT_ID="${1:?Usage: set_auth.sh <GOOGLE_CLIENT_ID> <emails,csv>}"
EMAILS="${2:?Usage: set_auth.sh <GOOGLE_CLIENT_ID> <emails,csv>}"

# ^|^ sets '|' as the entry delimiter so the commas inside EMAILS are preserved
# (gcloud otherwise splits env entries on commas).
"$GCLOUD" run services update "$SERVICE" --region="$REGION" \
  --update-env-vars="^|^GOOGLE_CLIENT_ID=${CLIENT_ID}|ALLOWED_EMAILS=${EMAILS}"

echo "Auth set. Allowed: $EMAILS"
