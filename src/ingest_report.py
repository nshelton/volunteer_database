"""Print a status report of the ingest cache (data/raw/*.json)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "data" / "records.json"
RAW_DIR = ROOT / "data" / "raw"

LABELS = {
    "ok": "ready for extraction",
    "thin": "fetched, very little text",
    "needs_session": "LinkedIn -- needs login",
    "access_denied": "not shared / no access",
    "error": "fetch failed",
}


def main() -> None:
    records = {r["id"]: r for r in json.loads(RECORDS.read_text())}
    rows = []
    counts: Counter[str] = Counter()
    for meta_path in sorted(RAW_DIR.glob("*.json")):
        m = json.loads(meta_path.read_text())
        rec = records.get(m["id"], {})
        rows.append((m["status"], m["id"], m["chars"], rec.get("name_hint"), m["url"]))
        counts[m["status"]] += 1

    order = ["ok", "thin", "needs_session", "access_denied", "error"]
    rows.sort(key=lambda r: (order.index(r[0]) if r[0] in order else 99, -r[2]))

    print(f"{'STATUS':14} {'CHARS':>6}  {'NAME / ID':28}  URL")
    print("-" * 100)
    for status, rid, chars, name, url in rows:
        label = (name or rid)[:28]
        print(f"{status:14} {chars:>6}  {label:28}  {(url or '')[:48]}")

    print("\nSummary")
    for k in order:
        if counts.get(k):
            print(f"  {counts[k]:3}  {k:14} {LABELS.get(k, '')}")
    ready = counts.get("ok", 0)
    total = sum(counts.values())
    print(f"\n{ready}/{total} ready for skill extraction.")


if __name__ == "__main__":
    main()
