// Single frontend over the volunteer database, which lives in a Google Sheet
// (see data.js). Modes: Browse (keyword + semantic search), Matchmake, Map
// (UMAP scatter), Skills (force-directed category graph), Table, Signups.
//
// This is the entry module: boot, mode switching, the shared controls, and
// the render dispatcher. State lives in state.js; each mode is its own module.

import { runWithAuth } from "../auth.js";
import { el, esc } from "./util.js";
import { S, OPPORTUNITIES, catLabel, catColor } from "./state.js";
import { loadData } from "./data.js";
import { embedProfiles } from "./semantic.js";
import { renderBrowse, renderSemantic, renderSimilar } from "./browse.js";
import { buildOppCards, renderMatch } from "./match.js";
import { renderMap } from "./map.js";
import { renderSkillsMode, wireSkillsControls, stopSkills } from "./skills.js";
import { renderTable } from "./table.js";
import { renderSignups } from "./signups.js";

async function boot() {
  await loadData();
  buildFilters();
  wireTheme();
  wireControls();
  render();
  // Semantic search, "find similar" and the map wait on this; keyword search
  // and everything else work meanwhile.
  embedProfiles().then(render);
}

function buildFilters() {
  const counts = {};
  for (const p of S.people) for (const c of p.categories) counts[c.category] = (counts[c.category] || 0) + 1;
  const box = document.getElementById("filter-chips");
  box.innerHTML = "";
  Object.keys(S.tax).filter((k) => counts[k]).sort((a, b) => counts[b] - counts[a]).forEach((k) => {
    const chip = el("span", "chip", `${esc(catLabel(k))}<span class="count">${counts[k]}</span>`);
    chip.style.setProperty("--c", catColor(k));
    chip.dataset.k = k;
    chip.onclick = () => { S.activeCats.has(k) ? S.activeCats.delete(k) : S.activeCats.add(k); chip.classList.toggle("active"); render(); };
    box.appendChild(chip);
  });
}

// The SVG views bake their colors in at draw time, so a theme flip has to
// re-render rather than just restyle.
function applyTheme(name) {
  document.documentElement.dataset.theme = name;
  document.getElementById("theme-btn").textContent = name === "dark" ? "☀" : "☾";
  try { localStorage.setItem("theme", name); } catch (_) {}
}

function wireTheme() {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  document.getElementById("theme-btn").onclick = () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    render();
  };
}

function wireControls() {
  let searchTimer = null;
  document.getElementById("search").addEventListener("input", (e) => {
    S.term = e.target.value.toLowerCase().trim();
    S.similarTo = null;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(render, 180);
  });
  const semBtn = document.getElementById("semantic");
  semBtn.onclick = () => {
    if (!S.emb) return;
    S.semantic = !S.semantic;
    semBtn.classList.toggle("active", S.semantic);
    S.similarTo = null;
    render();
  };
  document.getElementById("nv-only").onclick = (e) => {
    S.nvOnly = !S.nvOnly; e.currentTarget.classList.toggle("active", S.nvOnly); render();
  };
  document.getElementById("clear").onclick = () => {
    S.activeCats.clear(); S.nvOnly = false;
    document.getElementById("nv-only").classList.remove("active");
    document.querySelectorAll("#filter-chips .chip").forEach((c) => c.classList.remove("active"));
    render();
  };

  const setMode = (m) => {
    S.mode = m;
    S.similarTo = null;
    const bare = m === "map" || m === "skills" || m === "signups";
    ["browse", "match", "map", "skills", "table", "signups"].forEach((v) =>
      document.getElementById("mode-" + v).classList.toggle("active", m === v));
    document.getElementById("match-controls").classList.toggle("hidden", m !== "match");
    document.getElementById("cat-section").classList.toggle("hidden", bare || m === "table");
    if (m === "match") document.getElementById("cat-section").open = true;
    document.getElementById("nv-only").classList.toggle("hidden", m !== "browse");
    document.getElementById("signup-toggle").classList.toggle("hidden", m !== "browse" && m !== "table");
    document.getElementById("map-controls").classList.toggle("hidden", m !== "map");
    document.getElementById("skills-controls").classList.toggle("hidden", m !== "skills");
    document.querySelector(".search-row").classList.toggle("hidden", bare);
    // Semantic ranking only applies to the browse grid; elsewhere the box is a
    // plain keyword filter, so don't offer a toggle that does nothing.
    document.getElementById("semantic").classList.toggle("hidden", m !== "browse");
    document.getElementById("search").placeholder =
      m === "match" ? "Keywords: houdini, real-time, pipeline…" : "Search name, skill, theme…";
    render();
  };
  document.getElementById("mode-browse").onclick = () => setMode("browse");
  document.getElementById("mode-match").onclick = () => setMode("match");
  document.getElementById("mode-map").onclick = () => setMode("map");
  document.getElementById("mode-skills").onclick = () => setMode("skills");
  document.getElementById("mode-table").onclick = () => setMode("table");
  document.getElementById("mode-signups").onclick = () => setMode("signups");
  document.getElementById("signup-toggle").onclick = (e) => {
    S.showSignups = !S.showSignups;
    e.currentTarget.classList.toggle("active", S.showSignups);
    render();
  };

  wireSkillsControls();

  buildOppCards();
  const ta = document.getElementById("opp-text");
  let oppTimer = null;
  ta.addEventListener("input", () => {
    S.oppText = ta.value;
    // Text diverged from the selected posting: it's a custom prompt now.
    if (S.activeOpp >= 0 && S.oppText !== OPPORTUNITIES[S.activeOpp].text) {
      S.activeOpp = -1;
      document.querySelectorAll("#opp-cards .opp-card").forEach((c) => c.classList.remove("active"));
    }
    clearTimeout(oppTimer);
    oppTimer = setTimeout(render, 400);
  });

  const modal = document.getElementById("modal");
  document.getElementById("modal-close").onclick = () => modal.classList.add("hidden");
  modal.onclick = (e) => { if (e.target === modal) modal.classList.add("hidden"); };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") modal.classList.add("hidden"); });
}

export function render() {
  if (S.mode !== "skills") stopSkills();
  document.getElementById("clear").classList.toggle("hidden", S.mode === "map" || S.mode === "skills" || !S.activeCats.size);
  document.getElementById("cards").classList.toggle("map-mode", S.mode === "map" || S.mode === "skills");
  document.getElementById("cards").classList.toggle("signups-mode", S.mode === "signups" || S.mode === "table");
  if (S.mode === "signups") return renderSignups();
  if (S.mode === "table") return renderTable();
  if (S.mode === "skills") return renderSkillsMode();
  if (S.mode === "map") return renderMap();
  if (S.mode === "match") return renderMatch();
  if (S.similarTo) return renderSimilar();
  if (S.semantic && S.term) return renderSemantic();
  return renderBrowse();
}

runWithAuth(boot);   // Google Sign-In gate, then the sheet grant
