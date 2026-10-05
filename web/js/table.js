// Table mode: every row of everything we hold on each person.

import { el, esc } from "./util.js";
import { S, catLabel } from "./state.js";
import { visiblePeople, matchesSearch, emailOf, isSignupOnly } from "./data.js";
import { openModal } from "./card.js";

const TABLE_COLS = [
  { key: "name", label: "Name", get: (p) => p.name },
  { key: "email", label: "Email", get: (p) => emailOf(p) },
  { key: "status", label: "Status", get: (p) => p.status },
  { key: "section", label: "Group", get: (p) => p.section },
  { key: "source", label: "Source", get: (p) => p.source_type },
  { key: "seniority", label: "Seniority", get: (p) => p.seniority },
  { key: "location", label: "Location", get: (p) => p.location },
  { key: "ncat", label: "Skills", num: true, get: (p) => p.categories.length },
  { key: "cats", label: "Top categories", get: (p) => [...new Set(p.categories.map((c) => catLabel(c.category)))].slice(0, 3).join(", ") },
  { key: "nthemes", label: "Themes", num: true, get: (p) => p.themes.length },
  { key: "pubs", label: "Pubs", num: true, get: (p) => (p.publications ? p.publications.works_count || 0 : 0) },
  { key: "signed", label: "Signed up", get: (p) => (p.signup ? (p.signup.timestamp || "").split(" ")[0] : "") },
  { key: "programs", label: "Program interests", get: (p) => (p.signup ? p.signup.programs : "") },
  { key: "committees", label: "Committee interests", get: (p) => (p.signup ? p.signup.committees : "") },
  { key: "notes", label: "Their notes", get: (p) => (p.signup ? p.signup.notes : "") },
  { key: "url", label: "Source URL", get: (p) => p.url },
];

export function renderTable() {
  const rows = visiblePeople().filter(matchesSearch);
  const col = TABLE_COLS.find((c) => c.key === S.tableSort.key) || TABLE_COLS[0];
  rows.sort((a, b) => {
    const x = col.get(a), y = col.get(b);
    const cmp = col.num ? (x || 0) - (y || 0) : String(x || "").localeCompare(String(y || ""));
    // Blanks sort last regardless of direction — an empty cell is never the
    // most interesting row.
    if (!col.num && !x !== !y) return !x ? 1 : -1;
    return S.tableSort.dir * cmp;
  });

  const stats = document.getElementById("stats");
  stats.textContent = `${rows.length} rows · ${TABLE_COLS.length} fields · click a header to sort, a row to open · `;
  const dl = el("a", "clear-link", "download CSV");
  dl.href = "#";
  dl.onclick = (e) => { e.preventDefault(); downloadCsv(rows); };
  stats.appendChild(dl);

  const box = document.getElementById("cards");
  box.innerHTML = "";
  const wrap = el("div", "table-wrap");
  const t = el("table", "db-table");
  const thead = el("thead");
  const hr = el("tr");
  TABLE_COLS.forEach((c) => {
    const th = el("th", c.num ? "num" : null,
      esc(c.label) + (S.tableSort.key === c.key ? (S.tableSort.dir > 0 ? " ▲" : " ▼") : ""));
    th.onclick = () => {
      S.tableSort = S.tableSort.key === c.key ? { key: c.key, dir: -S.tableSort.dir } : { key: c.key, dir: 1 };
      renderTable();
    };
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  t.appendChild(thead);

  const tb = el("tbody");
  rows.forEach((p) => {
    const tr = el("tr");
    if (isSignupOnly(p)) tr.classList.add("row-signup");
    TABLE_COLS.forEach((c) => {
      const v = c.get(p);
      const td = el("td", c.num ? "num" : null, esc(v == null ? "" : String(v)));
      td.title = String(v == null ? "" : v);
      tr.appendChild(td);
    });
    tr.onclick = () => openModal(p);
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  wrap.appendChild(t);
  box.appendChild(wrap);
  if (!rows.length) box.appendChild(el("div", "empty", "No rows match."));
}

function downloadCsv(rows) {
  const q = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
  const lines = [TABLE_COLS.map((c) => q(c.label)).join(",")];
  rows.forEach((p) => lines.push(TABLE_COLS.map((c) => q(c.get(p))).join(",")));
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "siggraph-volunteers.csv";
  a.click();
  URL.revokeObjectURL(url);
}
