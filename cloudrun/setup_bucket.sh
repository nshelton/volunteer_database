#!/usr/bin/env bash
# One-time: create the private bucket that holds the mutable state (signups.json
# mirrored from the form sheet, links.json the hand-made email->volunteer join),
# let the Cloud Run service account read/write it, and point the service at it.
#
# Re-runnable: an existing bucket and a repeated IAM binding are both no-ops.
#
#   bash cloudrun/setup_bucket.sh [SHEET_ID]
#
set -euo pipefail

GCLOUD="$(command -v gcloud || echo "$HOME/google-cloud-sdk/bin/gcloud")"
PROJECT=siggraph-vdc
REGION=us-central1
SERVICE=siggraph-vdc
BUCKET="${PROJECT}-state"
# The "SIGGRAPH Volunteering (Responses)" form sheet.
SHEET_ID="${1:-1hsEayVVGH-_1JBLVLlW1xNK3UGlgIxg2_afOIf9hHH4}"

echo "==> Creating gs://$BUCKET (skipped if it exists)"
"$GCLOUD" storage buckets create "gs://$BUCKET" \
  --project="$PROJECT" --location="$REGION" --uniform-bucket-level-access 2>/dev/null \
  || echo "    already exists"

# Cloud Run's runtime identity: whatever the service is configured with, else
# the project's default compute service account.
SA="$("$GCLOUD" run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --format='value(spec.template.spec.serviceAccountName)')"
if [ -z "$SA" ]; then
  NUM="$("$GCLOUD" projects describe "$PROJECT" --format='value(projectNumber)')"
  SA="${NUM}-compute@developer.gserviceaccount.com"
fi
echo "==> Granting objectAdmin on the bucket to $SA"
"$GCLOUD" storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --project="$PROJECT" --member="serviceAccount:$SA" --role=roles/storage.objectAdmin >/dev/null

echo "==> Pointing $SERVICE at the bucket and the sheet"
"$GCLOUD" run services update "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --update-env-vars="GCS_BUCKET=${BUCKET},SHEET_ID=${SHEET_ID}"

echo
echo "Done. Bucket: gs://$BUCKET   Sheet: $SHEET_ID"
echo
echo "Still needed once, by hand, in the Google Cloud console:"
echo "  1. Enable the Sheets API:"
echo "     https://console.cloud.google.com/apis/library/sheets.googleapis.com?project=$PROJECT"
echo "  2. Add the scope, under Google Auth Platform > Data Access:"
echo "     https://console.cloud.google.com/auth/scopes?project=$PROJECT"
echo "     https://www.googleapis.com/auth/spreadsheets.readonly"
echo "  3. Add EVERY allowlisted email as a test user, under Audience:"
echo "     https://console.cloud.google.com/auth/audience?project=$PROJECT"
echo
echo "Step 3 is not optional and not implied by step 2. spreadsheets.readonly is"
echo "a sensitive scope, so while the app is in Testing only listed test users"
echo "may grant it -- including you, the project owner. Skipping it gives"
echo "'Error 403: access_denied' on Sync while plain sign-in still works."
echo "Test users then see a one-time 'unverified app' warning: Advanced > Go to."
echo "Do NOT publish the app to production to silence that warning -- an External"
echo "app with a sensitive scope then requires full Google verification review."
