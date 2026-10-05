"""Parse volunteer_list.txt into structured records.

Input: a plain-text file where section headers are non-URL lines and each
volunteer is a URL line (with occasional "Can't find ..." notes).

Output: data/records.json -- a list of records:
    {
      "id":          stable slug, unique within the file,
      "url":         the source URL (or null for unresolved notes),
      "source_type": linkedin | drive | github | pdf | web | unresolved,
      "section":     the section header this entry fell under,
      "name_hint":   best-effort name guessed from the URL slug (or note),
      "note":        free text for unresolved entries
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SRC_TXT = ROOT / "volunteer_list.txt"
OUT_JSON = ROOT / "data" / "records.json"

# Header lines mapped to a clean section label (matched on a lowercased
# prefix, since the source titles are long and inconsistent).
_HEADER_ALIASES = (
    ("list of new-volunteer resumes", "new-volunteer"),
)

# Pure document/meta lines that are neither a section header nor a person.
_SKIP_LINES = {
    "linkedin for skills matrix",
    "have not included duplicates",
}


def classify(url: str) -> str:
    """Bucket a URL into a fetch strategy."""
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower()
    # linkedin.com and country subdomains (au., cn., ca., de., fr., sg., ...);
    # also tolerate the "linked.com" typo present in the source file.
    if "linkedin.com" in host or host == "linked.com" or ".linkedin." in host:
        return "linkedin"
    if "drive.google.com" in host:
        return "drive"
    if path.endswith(".pdf"):
        return "pdf"
    if "github.com" in host or host.endswith("github.io"):
        return "github"
    return "web"


def name_from_url(url: str, source_type: str) -> str | None:
    """Best-effort display name from a URL slug. The LLM later overrides this
    from the actual resume text; this is only for a readable pre-extraction
    label."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path

    slug = None
    if source_type == "linkedin":
        m = re.search(r"/in/([^/?#]+)", path)
        if m:
            slug = m.group(1)
            # strip the trailing hash LinkedIn appends, e.g. jane-doe-9b2372339
            slug = re.sub(r"-?\b[0-9a-f]{6,}\b$", "", slug)
            slug = re.sub(r"-\d+$", "", slug)
    elif host.endswith("github.io"):
        slug = host.split(".github.io")[0]
    elif source_type in ("pdf", "github"):
        # filename like JaneDoe_Resume.pdf or jane-doe-resume.pdf
        fname = Path(path).stem
        fname = re.sub(r"(?i)[-_]?(resume|cv)$", "", fname)
        if fname and not re.fullmatch(r"[0-9a-f_]+", fname):
            slug = fname
    elif source_type == "web":
        # e.g. jdoe.framer.media, janedoe.com
        label = host.split(".")[0]
        if label not in ("www", "drive", "resume"):
            slug = label

    if not slug:
        return None
    # Normalise separators, drop digits, title-case.
    words = re.split(r"[-_.]+", slug)
    words = [w for w in words if w and not w.isdigit()]
    if not words:
        return None
    return " ".join(w.capitalize() for w in words)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse(text: str) -> list[dict]:
    records: list[dict] = []
    section = "new-volunteer"
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        low = line.lower()
        if low in _SKIP_LINES:
            continue

        is_url = line.startswith("http")
        # A note about a person we couldn't locate (but not the meta dup line,
        # which is filtered above).
        note_match = re.match(r"(?i)can.?t find\b", line)

        if not is_url and not note_match:
            # Section header.
            for prefix, label in _HEADER_ALIASES:
                if low.startswith(prefix):
                    section = label
                    break
            else:
                section = line
            continue

        if is_url and line in seen_urls:
            # Duplicate URL (source file contains a few) -- skip.
            continue

        rec: dict
        if is_url:
            seen_urls.add(line)
            stype = classify(line)
            name_hint = name_from_url(line, stype)
            base = slugify(name_hint) if name_hint else slugify(
                urlparse(line).path or urlparse(line).hostname or "entry"
            )
            rec = {
                "url": line,
                "source_type": stype,
                "section": section,
                "name_hint": name_hint,
                "note": None,
            }
        else:
            # Unresolved note, e.g. "Can't find Aaron Hosier".
            base = slugify(line) or "note"
            rec = {
                "url": None,
                "source_type": "unresolved",
                "section": section,
                "name_hint": None,
                "note": line,
            }

        # Ensure a unique, stable id.
        rec_id = base or "entry"
        n = 2
        while rec_id in seen_ids:
            rec_id = f"{base}-{n}"
            n += 1
        seen_ids.add(rec_id)
        rec = {"id": rec_id, **rec}
        records.append(rec)

    return records


def main() -> None:
    text = SRC_TXT.read_text(encoding="utf-8")
    records = parse(text)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    by_type: dict[str, int] = {}
    for r in records:
        by_type[r["source_type"]] = by_type.get(r["source_type"], 0) + 1
    print(f"Parsed {len(records)} records -> {OUT_JSON.relative_to(ROOT)}")
    for k in sorted(by_type):
        print(f"  {k:12} {by_type[k]}")


if __name__ == "__main__":
    main()
