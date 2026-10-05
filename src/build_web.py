"""Emit web/data/taxonomy.json, the only data file the site ships with.

The volunteer database itself is a Google Sheet the browser reads directly, so
nothing personal is built into web/.
"""

from __future__ import annotations

import json
from pathlib import Path

from taxonomy import CATEGORIES, CATEGORY_GROUP, GROUPS

WEB_DATA = Path(__file__).resolve().parent.parent / "web" / "data"


def main() -> None:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    taxonomy = {
        "categories": {
            k: {"label": label, "desc": desc, "group": CATEGORY_GROUP.get(k)}
            for k, (label, desc) in CATEGORIES.items()
        },
        "groups": {g: {"label": label, "color": color} for g, (label, color) in GROUPS.items()},
    }
    (WEB_DATA / "taxonomy.json").write_text(
        json.dumps(taxonomy, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Built web/data/taxonomy.json with {len(taxonomy['categories'])} categories.")


if __name__ == "__main__":
    main()
