// Matchmake mode: rank volunteers against an opportunity posting or a
// free-text description of one.

import { el, esc, dot } from "./util.js";
import { S, OPPORTUNITIES, LEVEL_WEIGHT, RESEARCHY, catLabel, catColor, levelOf } from "./state.js";
import { visiblePeople } from "./data.js";
import { oppVec } from "./semantic.js";
import { card } from "./card.js";
import { render } from "./main.js";

// Opportunity postings as clickable cards in the match panel. Selecting one
// loads its description, required categories, and keywords; clicking again
// clears it.
export function buildOppCards() {
  const box = document.getElementById("opp-cards");
  OPPORTUNITIES.forEach((o, i) => {
    const c = el("div", "opp-card");
    c.appendChild(el("div", "opp-org", esc(o.org)));
    c.appendChild(el("div", "opp-title", esc(o.title)));
    c.appendChild(el("p", "opp-desc", esc(o.text)));
    const row = el("div", "cat-row");
    o.cats.slice(0, 4).forEach((k) => {
      const chip = el("span", "chip", esc(catLabel(k)));
      chip.style.setProperty("--c", catColor(k));
      row.appendChild(chip);
    });
    if (o.cats.length > 4) row.appendChild(el("span", "more", `+${o.cats.length - 4}`));
    c.appendChild(row);
    c.onclick = () => selectOpp(S.activeOpp === i ? -1 : i);
    box.appendChild(c);
  });
}

function selectOpp(i) {
  S.activeOpp = i;
  const o = i >= 0 ? OPPORTUNITIES[i] : null;
  document.querySelectorAll("#opp-cards .opp-card").forEach((c, j) => c.classList.toggle("active", j === i));
  S.oppText = o ? o.text : "";
  document.getElementById("opp-text").value = S.oppText;
  S.activeCats.clear();
  if (o) o.cats.forEach((k) => S.activeCats.add(k));
  document.querySelectorAll("#filter-chips .chip").forEach((c) => c.classList.toggle("active", S.activeCats.has(c.dataset.k)));
  const s = document.getElementById("search");
  s.value = o ? o.keywords : "";
  S.term = s.value.toLowerCase().trim();
  render();
}

// Rank volunteers against an opportunity: semantic similarity between its
// description and each person's profile embedding, plus selected categories
// (weighted by the person's level), keyword hits, and a publication bonus for
// research-leaning needs.
export async function renderMatch() {
  const cats = [...S.activeCats];
  const keywords = S.term ? S.term.split(/[,\s]+/).filter(Boolean) : [];
  const text = S.oppText.trim();
  let qv = null;
  if (text && S.emb) {
    document.getElementById("stats").textContent = "Embedding opportunity description…";
    try { qv = await oppVec(text); } catch (_) { qv = null; }
    if (S.mode !== "match" || text !== S.oppText.trim()) return;  // state changed while embedding
  }
  const researchNeed = !cats.length || cats.some((k) => RESEARCHY.has(k));
  const scored = visiblePeople().map((p) => {
    let s = 0; const why = [];
    if (qv && S.emb.vectors[p.id]) {
      const sim = dot(qv, S.emb.vectors[p.id]);
      s += sim * 30;
      why.push(`${Math.round(sim * 100)}% similar`);
    }
    for (const k of cats) {
      const lvl = levelOf(p, k);
      if (lvl) { s += LEVEL_WEIGHT[lvl] * 4; why.push(`${catLabel(k)} (${lvl})`); }
    }
    const hay = [p.headline, p.summary, p.skills.join(" "), p.tools.join(" "), p.roles.join(" "), p.themes.join(" ")].join(" ").toLowerCase();
    for (const kw of keywords) if (hay.includes(kw)) { s += 2; why.push(`“${kw}”`); }
    if (p.publications && researchNeed) {
      const w = p.publications.works_count || 0;
      const b = Math.min(w, 200) / 40;
      if (b > 0) { s += b; why.push(`${w} pubs`); }
    }
    return { p, s, why };
  }).filter((x) => x.s > 0).sort((a, b) => b.s - a.s)
    .slice(0, qv ? 40 : Infinity);  // semantic gives everyone a score; keep the head

  const need = [
    S.activeOpp >= 0 ? OPPORTUNITIES[S.activeOpp].title : text ? "custom prompt" : "",
    ...cats.map(catLabel), ...keywords.map((k) => `“${k}”`),
  ].filter(Boolean).join(", ") || "(nothing selected)";
  document.getElementById("stats").textContent =
    scored.length ? `${scored.length} suggested · need: ${need}` : `No matches · need: ${need}`;
  const box = document.getElementById("cards");
  box.innerHTML = "";
  if (!scored.length) { box.appendChild(el("div", "empty", "Pick an opportunity, describe your own, or select required skills to rank volunteers.")); return; }
  for (const { p, s, why } of scored) box.appendChild(card(p, { score: s, why }));
}
