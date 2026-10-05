"""SIGGRAPH volunteer site — Google Sign-In gated.

The UI shell (HTML/CSS/JS + the Google button) is served openly because it
contains no sensitive data. The volunteer database is not here at all: it is a
Google Sheet that the browser reads with the signed-in user's own access, so
the sheet's sharing settings decide who sees it.

What this server holds is the signup state under /data/*, served ONLY to
requests carrying a valid Google ID token whose verified email is on the
allowlist. Both files are mutable and live in GCS rather than the image:

    signups.json   mirror of the Google Form responses sheet, pushed by a
                   signed-in user clicking "Sync" (the browser reads the sheet
                   with that user's own Google access token).
    links.json     the human-curated join { email -> volunteer_id }. The form
                   sheet is keyed by email and volunteers.json is keyed by a
                   URL slug, and they share no common field, so the mapping is
                   made by hand in the UI. Written under a generation
                   precondition so simultaneous editors can't clobber silently.

The one other file under /data/, taxonomy.json, is baked into the image by
build_web.py. It holds no personal data; the frontend fetches it first to probe
the allowlist.

Environment:
    GOOGLE_CLIENT_ID   OAuth 2.0 Web client ID (also used by the frontend)
    ALLOWED_EMAILS     comma-separated allowlist of Google emails
    GCS_BUCKET         bucket holding signups.json + links.json
    SHEET_ID           Google Sheets file ID of the Form responses sheet
    DB_SHEET_ID        Google Sheets file ID of the volunteer database
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request, send_from_directory
from google.api_core import exceptions as gcloud_exc
from google.auth.transport import requests as ga_requests
from google.cloud import storage
from google.oauth2 import id_token as google_id_token

app = Flask(__name__, static_folder=None)

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
ALLOWED = {
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EMAILS", "").split(",")
    if e.strip()
}
BUCKET = os.environ.get("GCS_BUCKET", "")
SHEET_ID = os.environ.get("SHEET_ID", "")
DB_SHEET_ID = os.environ.get("DB_SHEET_ID", "")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
DATA_DIR = os.path.join(WEB_DIR, "data")

_GA_REQUEST = ga_requests.Request()
_VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Served from GCS instead of the image.
SIGNUPS = "signups.json"
LINKS = "links.json"
MUTABLE = {SIGNUPS, LINKS}

# Form response columns, in sheet order. The sheet's real headers are whole
# paragraphs, so we key off position and keep short names for the UI.
COLUMNS = [
    "timestamp", "email", "is_new", "past_experience", "wants_committee",
    "committees", "membership", "conferences", "programs", "notes",
]

_storage = None


def _blob(name):
    global _storage
    if _storage is None:
        _storage = storage.Client()
    return _storage.bucket(BUCKET).blob(name)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def verified_email(req) -> str | None:
    """Return the allowlisted email if the request carries a valid Google ID
    token for an approved user, else None."""
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):]
    try:
        info = google_id_token.verify_oauth2_token(token, _GA_REQUEST, CLIENT_ID)
    except Exception:
        return None
    if info.get("iss") not in _VALID_ISSUERS:
        return None
    if not info.get("email_verified"):
        return None
    email = (info.get("email") or "").lower()
    return email if email in ALLOWED else None


def read_state(name: str) -> dict:
    """Current contents of a mutable file, or an empty skeleton if it has never
    been written (fresh bucket, or no bucket configured at all)."""
    empty = {"signups": [], "synced_at": None} if name == SIGNUPS else {"links": {}, "updated_at": None}
    if not BUCKET:
        return empty
    try:
        return json.loads(_blob(name).download_as_bytes())
    except gcloud_exc.NotFound:
        return empty


def write_links(mutate, tries: int = 5) -> dict:
    """Read-modify-write links.json under a generation precondition.

    Anyone on the allowlist may edit any link and the last write wins — but a
    precondition means a losing write is retried against fresh state rather
    than silently dropping the other person's edit.
    """
    for _ in range(tries):
        blob = _blob(LINKS)
        try:
            state = json.loads(blob.download_as_bytes())
            generation = blob.generation
        except gcloud_exc.NotFound:
            state = {"links": {}, "updated_at": None}
            generation = 0  # precondition: create only if still absent
        mutate(state)
        try:
            blob.upload_from_string(
                json.dumps(state, indent=2, ensure_ascii=False),
                content_type="application/json",
                if_generation_match=generation,
            )
            return state
        except gcloud_exc.PreconditionFailed:
            continue
    raise RuntimeError("links.json is being edited too fast to settle")


# ---- public: UI shell + auth config ----
@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/auth-config.json")
def auth_config():
    # Client ID is not a secret; the frontend needs it to init Google Sign-In.
    # The sheet ids likewise — reading them still requires the user's own access.
    return jsonify({"client_id": CLIENT_ID, "sheet_id": SHEET_ID, "db_sheet_id": DB_SHEET_ID})


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


# ---- protected: signup state + taxonomy ----
@app.route("/data/<path:path>")
def data(path):
    if not CLIENT_ID or not ALLOWED:
        return Response("Auth not configured.", status=503)
    if not verified_email(request):
        return Response("Not authorized.", status=403)
    if path in MUTABLE:
        return jsonify(read_state(path))
    return send_from_directory(DATA_DIR, path)


# ---- protected: mutations ----
@app.route("/api/signups", methods=["POST"])
def put_signups():
    """Replace the signups mirror with rows the caller read from the sheet.

    The browser does the reading (with the signed-in user's own Google token,
    since the sheet is owned by someone else and we have no service-account
    access to it) and posts the raw `values` here to persist for everyone.
    """
    email = verified_email(request)
    if not email:
        return Response("Not authorized.", status=403)
    if not BUCKET:
        return Response("No bucket configured.", status=503)

    values = (request.get_json(silent=True) or {}).get("values") or []
    rows = []
    for row in values[1:]:  # values[0] is the header paragraph row
        rec = {key: (row[i].strip() if i < len(row) and row[i] else "")
               for i, key in enumerate(COLUMNS)}
        if rec["email"]:
            rec["email"] = rec["email"].lower()
            rows.append(rec)

    # One person, one card: a repeat submission supersedes the earlier one.
    # Form responses are appended chronologically, so last occurrence wins.
    deduped = {}
    for rec in rows:
        deduped[rec["email"]] = rec

    state = {
        "signups": list(deduped.values()),
        "row_count": len(rows),
        "synced_at": now_iso(),
        "synced_by": email,
        "sheet_id": SHEET_ID,
    }
    _blob(SIGNUPS).upload_from_string(
        json.dumps(state, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
    return jsonify(state)


@app.route("/api/link", methods=["POST"])
def put_link():
    """Associate a signup email with a volunteers.json record (or clear it).

    Any allowlisted user may set any link — this is a small trusted group and
    the mapping is easier to fix than to gate.
    """
    email = verified_email(request)
    if not email:
        return Response("Not authorized.", status=403)
    if not BUCKET:
        return Response("No bucket configured.", status=503)

    body = request.get_json(silent=True) or {}
    key = (body.get("email") or "").strip().lower()
    volunteer_id = (body.get("volunteer_id") or "").strip()
    if not key:
        return Response("Missing email.", status=400)

    def mutate(state):
        links = state.setdefault("links", {})
        if volunteer_id:
            links[key] = {"volunteer_id": volunteer_id, "by": email, "at": now_iso()}
        else:
            links.pop(key, None)
        state["updated_at"] = now_iso()
        state["updated_by"] = email

    return jsonify(write_links(mutate))


# ---- public: other static assets (css/js) ----
@app.route("/<path:path>")
def assets(path):
    if path.startswith("data/"):  # safety: never serve data via this route
        return Response("Not authorized.", status=403)
    return send_from_directory(WEB_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
