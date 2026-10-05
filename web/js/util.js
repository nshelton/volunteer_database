// Generic DOM + string helpers. No app state.

export const el = (t, c, html) => { const e = document.createElement(t); if (c) e.className = c; if (html !== undefined) e.innerHTML = html; return e; };
export const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const dot = (a, b) => { let s = 0; const n = Math.min(a.length, b.length); for (let i = 0; i < n; i++) s += a[i] * b[i]; return s; };
// The Map and Skills views paint SVG from JS, so their colors can't live in a
// stylesheet rule — read the theme tokens instead of hardcoding them.
export const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// Decode HTML entities in source strings (e.g. "&amp;") before re-escaping.
export function decode(s) { if (!s) return ""; const t = document.createElement("textarea"); t.innerHTML = s; return t.value; }

// External link that doesn't trigger the card's open-modal click.
export function extLink(href, text) {
  const a = el("a", "pub-link", esc(text));
  a.href = href; a.target = "_blank"; a.rel = "noopener";
  a.onclick = (e) => e.stopPropagation();
  return a;
}

export function relTime(iso) {
  if (!iso) return "never";
  const mins = (Date.now() - new Date(iso).getTime()) / 60000;
  if (mins < 2) return "just now";
  if (mins < 90) return `${Math.round(mins)}m ago`;
  if (mins < 36 * 60) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}
