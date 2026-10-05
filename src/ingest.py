"""Ingest pipeline: fetch raw text for each volunteer record.

Reads data/records.json and, for every record with a URL, fetches the resume /
profile text and caches it to:

    data/raw/<id>.txt    -- extracted plain text
    data/raw/<id>.json   -- {id, url, source_type, status, chars, strategy, error}

The cache makes the whole thing idempotent: re-running only re-fetches records
that have no successful cache entry yet (use --force to refetch everything,
or --only <id> to target one).

LinkedIn records are intentionally skipped here -- they need an authenticated
browser session and are handled by scrape_linkedin.py. They're marked with
status "needs_session" so the dashboard can show what's still pending.

Strategies:
    pdf / github-pdf  -> download bytes, extract text with pdfplumber
    web / github-page -> httpx + BeautifulSoup; if the page is JS-heavy and
                          yields too little text, re-render with Playwright
    drive             -> public "uc?export=download" endpoint, then pdf/html

Usage:
    python src/ingest.py                 # fetch all not-yet-cached
    python src/ingest.py --force         # refetch everything
    python src/ingest.py --only jdoe  # one record by id
    python src/ingest.py --no-render     # disable Playwright fallback
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx
import pdfplumber
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "data" / "records.json"
RAW_DIR = ROOT / "data" / "raw"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

# Below this many characters we assume the static fetch failed to capture a
# JS-rendered page and try Playwright instead.
MIN_USEFUL_CHARS = 400


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #
def pdf_to_text(data: bytes) -> str:
    out: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out).strip()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "head"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines / whitespace.
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def looks_like_pdf(data: bytes, content_type: str) -> bool:
    return data[:5] == b"%PDF-" or "application/pdf" in content_type.lower()


# --------------------------------------------------------------------------- #
# URL normalisation
# --------------------------------------------------------------------------- #
def normalize_url(url: str, source_type: str) -> str:
    """Rewrite a few host-specific URLs into directly downloadable forms."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    # github.com/<u>/<r>/blob/<branch>/<path> -> raw.githubusercontent.com/...
    if "github.com" in host and "/blob/" in parsed.path:
        raw_path = parsed.path.replace("/blob/", "/", 1)
        return f"https://raw.githubusercontent.com{raw_path}"

    # Google Drive share links -> direct download endpoint.
    if "drive.google.com" in host:
        file_id = None
        m = re.search(r"/file/d/([^/]+)", parsed.path)
        if m:
            file_id = m.group(1)
        else:
            file_id = (parse_qs(parsed.query).get("id") or [None])[0]
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}"

    return url


# --------------------------------------------------------------------------- #
# Fetchers
# --------------------------------------------------------------------------- #
def fetch_static(url: str) -> tuple[str, str]:
    """Return (text, strategy). Raises on hard failure."""
    with httpx.Client(
        headers=HEADERS, follow_redirects=True, timeout=30.0
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content
        ctype = resp.headers.get("content-type", "")

    if looks_like_pdf(data, ctype):
        return pdf_to_text(data), "httpx+pdf"
    return html_to_text(data.decode(resp.encoding or "utf-8", "replace")), "httpx+html"


def fetch_rendered(url: str) -> tuple[str, str]:
    """Render a JS-heavy page with Playwright and return (text, strategy).

    Imported lazily so the static path doesn't pay the import cost.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(1500)
            html = page.content()
        finally:
            browser.close()
    return html_to_text(html), "playwright+html"


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def cache_paths(rec_id: str) -> tuple[Path, Path]:
    return RAW_DIR / f"{rec_id}.txt", RAW_DIR / f"{rec_id}.json"


def is_cached_ok(rec_id: str) -> bool:
    txt, meta = cache_paths(rec_id)
    if not (txt.exists() and meta.exists()):
        return False
    try:
        return json.loads(meta.read_text())["status"] == "ok"
    except Exception:
        return False


def write_cache(rec: dict, text: str, status: str, strategy: str, error: str | None):
    txt, meta = cache_paths(rec["id"])
    txt.write_text(text or "", encoding="utf-8")
    meta.write_text(
        json.dumps(
            {
                "id": rec["id"],
                "url": rec["url"],
                "source_type": rec["source_type"],
                "status": status,
                "chars": len(text or ""),
                "strategy": strategy,
                "error": error,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def ingest_one(rec: dict, allow_render: bool) -> dict:
    url = normalize_url(rec["url"], rec["source_type"])
    text, strategy, error, status = "", "", None, "error"

    try:
        text, strategy = fetch_static(url)
        status = "ok"
    except Exception as e:  # noqa: BLE001 - record the failure, keep going
        error = f"static: {type(e).__name__}: {e}"

    # JS-heavy or blocked page -> try a real browser render.
    needs_render = status != "ok" or len(text) < MIN_USEFUL_CHARS
    if needs_render and allow_render and rec["source_type"] in ("web", "github", "drive"):
        try:
            r_text, r_strategy = fetch_rendered(rec["url"])
            if len(r_text) > len(text):
                text, strategy, status, error = r_text, r_strategy, "ok", None
        except Exception as e:  # noqa: BLE001
            error = (error or "") + f" | render: {type(e).__name__}: {e}"

    # Google Drive returns its sign-in page (HTTP 200) for files that aren't
    # link-shared. Detect that so it's reported as denied, not "ok".
    if "Sign in" in text[:1500] and "Google Drive" in text[:1500]:
        status, error = "access_denied", "drive file not shared publicly"

    if status == "ok" and len(text) < MIN_USEFUL_CHARS:
        status = "thin"  # fetched but suspiciously little text -- flag for review

    write_cache(rec, text, status, strategy, error)
    return {"id": rec["id"], "status": status, "chars": len(text), "strategy": strategy}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="refetch even if cached")
    ap.add_argument("--only", help="only this record id")
    ap.add_argument("--no-render", action="store_true", help="disable Playwright fallback")
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    records = json.loads(RECORDS.read_text())

    targets = []
    for rec in records:
        if args.only and rec["id"] != args.only:
            continue
        if rec["source_type"] == "unresolved":
            continue
        if rec["source_type"] == "linkedin":
            # Defer to the authenticated scraper.
            if not is_cached_ok(rec["id"]):
                write_cache(rec, "", "needs_session", "linkedin", None)
            continue
        if not args.force and is_cached_ok(rec["id"]):
            continue
        targets.append(rec)

    if not targets:
        print("Nothing to fetch (all cached, or use --force).")
        return

    print(f"Fetching {len(targets)} record(s)...\n")
    summary: dict[str, int] = {}
    for i, rec in enumerate(targets, 1):
        result = ingest_one(rec, allow_render=not args.no_render)
        summary[result["status"]] = summary.get(result["status"], 0) + 1
        flag = {"ok": "OK ", "thin": "THIN", "error": "ERR "}.get(result["status"], "??? ")
        print(
            f"[{i:2}/{len(targets)}] {flag} {rec['id'][:30]:30} "
            f"{result['chars']:>6} chars  {result['strategy']}"
        )

    print("\nSummary:", dict(summary))
    print(f"Cache: {RAW_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
