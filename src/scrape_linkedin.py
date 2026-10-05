"""Authenticated LinkedIn scraper (manual login + slow, human-paced fetch).

This uses a PERSISTENT Playwright browser profile so you log in ONCE by hand
(handling any 2FA / captcha yourself) and the session is reused for fetching.

    # 1) one-time: open a real browser, log in, press Enter
    python src/scrape_linkedin.py login

    # 2) fetch profiles into the same raw-text cache the resumes use
    python src/scrape_linkedin.py scrape
    python src/scrape_linkedin.py scrape --limit 5      # do a few at a time
    python src/scrape_linkedin.py scrape --only jdoe

Then run extraction as usual:  PYTHONPATH=src python src/extract.py

IMPORTANT / ethics:
  * Automating a logged-in LinkedIn session is against LinkedIn's User
    Agreement. Use your own (ideally secondary) account, at small scale, for
    this internal volunteer database only.
  * The scraper paces itself with random human-like delays and STOPS at the
    first sign of a checkpoint/auth wall to protect your account.

Headed mode needs a display. Run the `login` step from your own desktop
terminal (e.g. type `! python src/scrape_linkedin.py login` in Claude Code, or
run it directly in a terminal on the machine with a screen).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "data" / "records.json"
RAW_DIR = ROOT / "data" / "raw"
PROFILE_DIR = ROOT / "data" / "linkedin_session"   # persistent browser profile (gitignored)

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

# Pacing between profile fetches (seconds). Slow on purpose.
DELAY_MIN, DELAY_MAX = 25, 55

AUTHWALL_MARKERS = ("authwall", "/login", "/checkpoint", "signup")

# --- anti-automation: LinkedIn/Google block browsers that advertise that they
# are automated ("this browser is not secure"). Strip those tells. ---
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]
STEALTH_IGNORE = ["--enable-automation"]
STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def _system_chromium() -> str | None:
    """Prefer a real installed Chromium/Chrome over Playwright's bundled build;
    LinkedIn's 'secure browser' check is happier with a genuine browser."""
    for path in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
                 "/usr/bin/chromium", "/usr/bin/chromium-browser"):
        if Path(path).exists():
            return path
    return None


def launch_context(p, headless: bool):
    """Launch a persistent context with automation tells removed."""
    exe = _system_chromium()
    kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1366, "height": 900},
        args=STEALTH_ARGS,
        ignore_default_args=STEALTH_IGNORE,
        locale="en-US",
    )
    if exe:
        kwargs["executable_path"] = exe   # use native UA of the real browser
    else:
        kwargs["user_agent"] = UA          # bundled Chromium -> supply a real UA
    ctx = p.chromium.launch_persistent_context(**kwargs)
    ctx.add_init_script(STEALTH_INIT)
    return ctx


def linkedin_records() -> list[dict]:
    records = json.loads(RECORDS.read_text())
    return [r for r in records if r["source_type"] == "linkedin" and r.get("url")]


def write_cache(rec: dict, text: str, status: str, error: str | None):
    (RAW_DIR / f"{rec['id']}.txt").write_text(text or "", encoding="utf-8")
    (RAW_DIR / f"{rec['id']}.json").write_text(
        json.dumps(
            {
                "id": rec["id"], "url": rec["url"], "source_type": "linkedin",
                "status": status, "chars": len(text or ""),
                "strategy": "playwright+linkedin", "error": error,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def is_done(rec_id: str) -> bool:
    meta = RAW_DIR / f"{rec_id}.json"
    if not meta.exists():
        return False
    try:
        return json.loads(meta.read_text())["status"] == "ok"
    except Exception:
        return False


def cmd_login() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("Opening a browser. Log into LinkedIn, then return here and press Enter.")
    with sync_playwright() as p:
        ctx = launch_context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        input("\n>>> Press Enter AFTER you have logged in and see your feed... ")
        # Verify session looks authenticated.
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        ok = "feed" in page.url and "login" not in page.url
        print("Session looks logged in." if ok else "WARNING: may not be logged in (check the browser).")
        ctx.close()
    print(f"Session saved to {PROFILE_DIR.relative_to(ROOT)}/. You can now run: scrape")


def extract_profile_text(page) -> str:
    """Grab the readable text of the profile main column."""
    # Try to expand truncated sections (best-effort; ignore failures).
    for sel in ['button:has-text("see more")', 'button:has-text("Show all")']:
        try:
            for btn in page.query_selector_all(sel)[:8]:
                btn.click(timeout=800)
                page.wait_for_timeout(200)
        except Exception:
            pass
    node = page.query_selector("main") or page.query_selector("body")
    text = node.inner_text() if node else ""
    # Collapse blank lines.
    return "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())


def cmd_scrape(limit: int | None, only: str | None) -> None:
    if not PROFILE_DIR.exists():
        sys.exit("No saved session. Run `python src/scrape_linkedin.py login` first.")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    todo = []
    for rec in linkedin_records():
        if only and rec["id"] != only:
            continue
        if not only and is_done(rec["id"]):
            continue
        todo.append(rec)
    if limit:
        todo = todo[:limit]
    if not todo:
        print("Nothing to scrape (all done, or use --only).")
        return

    print(f"Scraping {len(todo)} LinkedIn profile(s), slowly. Ctrl-C to stop.\n")
    done = blocked = 0
    with sync_playwright() as p:
        ctx = launch_context(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for i, rec in enumerate(todo, 1):
                try:
                    page.goto(rec["url"], wait_until="domcontentloaded", timeout=40000)
                    page.wait_for_timeout(random.randint(2500, 4500))
                    cur = page.url.lower()
                    if any(m in cur for m in AUTHWALL_MARKERS):
                        write_cache(rec, "", "needs_session", "hit auth wall / checkpoint")
                        blocked += 1
                        print(f"[{i:2}/{len(todo)}] WALL {rec['id']} -> session invalid, STOPPING.")
                        print("    Re-run `login` (your session expired or LinkedIn flagged it).")
                        break
                    text = extract_profile_text(page)
                    if len(text) < 200:
                        write_cache(rec, text, "thin", "very little text")
                        print(f"[{i:2}/{len(todo)}] THIN {rec['id']} ({len(text)} chars)")
                    else:
                        write_cache(rec, text, "ok", None)
                        done += 1
                        print(f"[{i:2}/{len(todo)}] OK   {rec['id']:28} {len(text)} chars")
                except Exception as e:  # noqa: BLE001
                    write_cache(rec, "", "error", f"{type(e).__name__}: {e}")
                    print(f"[{i:2}/{len(todo)}] ERR  {rec['id']}: {e}")

                if i < len(todo):
                    wait = random.randint(DELAY_MIN, DELAY_MAX)
                    print(f"       …waiting {wait}s")
                    time.sleep(wait)
        finally:
            ctx.close()

    print(f"\nDone: {done} ok, {blocked} blocked. Next: PYTHONPATH=src python src/extract.py")


def main() -> None:
    ap = argparse.ArgumentParser(description="Authenticated LinkedIn scraper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="open a browser to log in once")
    sp = sub.add_parser("scrape", help="fetch profiles using the saved session")
    sp.add_argument("--limit", type=int, help="max profiles this run")
    sp.add_argument("--only", help="single record id")
    args = ap.parse_args()

    if args.cmd == "login":
        cmd_login()
    elif args.cmd == "scrape":
        cmd_scrape(args.limit, args.only)


if __name__ == "__main__":
    main()
