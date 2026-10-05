// Browse mode: the card grid, keyword + semantic search, and "find similar".

import { el, dot } from "./util.js";
import { S, catLabel } from "./state.js";
import { visiblePeople, matchesSearch, isSignupOnly } from "./data.js";
import { embedQuery } from "./semantic.js";
import { card } from "./card.js";
import { render } from "./main.js";

export function renderBrowse() {
  const sel = [...S.activeCats];
  const pool = visiblePeople();
  const list = pool.filter((p) => {
    if (S.nvOnly && p.status !== "applied") return false;
    if (sel.length && !sel.every((k) => p.categories.some((c) => c.category === k))) return false;
    return matchesSearch(p);
  });
  const nSignup = list.filter(isSignupOnly).length;
  document.getElementById("stats").textContent =
    `${list.length} of ${pool.length} volunteers` +
    (nSignup ? ` · ${nSignup} signup${nSignup === 1 ? "" : "s"} with no profile yet` : "") +
    (sel.length ? ` · ${sel.map(catLabel).join(", ")}` : "");
  list.sort((a, b) => a._rand - b._rand);
  const box = document.getElementById("cards");
  box.innerHTML = "";
  if (!list.length) { box.appendChild(el("div", "empty", "No volunteers match.")); return; }
  for (const p of list) box.appendChild(card(p));
}

// Free-text semantic search: embed the query in-browser, rank people by cosine
// similarity to their precomputed vectors.
export async function renderSemantic() {
  if (!S.emb) return renderBrowse();
  const box = document.getElementById("cards");
  const myTerm = S.term;
  document.getElementById("stats").textContent = `semantic search for “${myTerm}”…`;
  box.innerHTML = "";
  box.appendChild(el("div", "empty", "Embedding query… (first run downloads a ~25 MB model, then it's cached)"));
  let qv;
  try { qv = await embedQuery(myTerm); }
  catch (e) { box.innerHTML = ""; box.appendChild(el("div", "empty", "Couldn't load the semantic model — check your connection.")); return; }
  if (S.term !== myTerm || S.mode !== "browse" || !S.semantic || S.similarTo) return;  // state changed while loading
  const ranked = S.people.filter((p) => S.emb.vectors[p.id])
    .map((p) => ({ p, s: dot(qv, S.emb.vectors[p.id]) }))
    .sort((a, b) => b.s - a.s).slice(0, 30);
  document.getElementById("stats").textContent = `semantic · top ${ranked.length} for “${myTerm}”`;
  box.innerHTML = "";
  ranked.forEach(({ p, s }) => box.appendChild(card(p, { score: Math.round(s * 100), why: [] })));
}

// "Find similar people": rank everyone by cosine to the seed person's vector.
export function renderSimilar() {
  const box = document.getElementById("cards");
  const q = S.emb && S.emb.vectors[S.similarTo];
  const seed = S.people.find((p) => p.id === S.similarTo);
  if (!q) { box.innerHTML = ""; box.appendChild(el("div", "empty", "No embedding for this person.")); return; }
  const ranked = S.people.filter((p) => p.id !== S.similarTo && S.emb.vectors[p.id])
    .map((p) => ({ p, s: dot(q, S.emb.vectors[p.id]) }))
    .sort((a, b) => b.s - a.s).slice(0, 20);
  const stats = document.getElementById("stats");
  stats.textContent = `Similar to ${seed ? seed.name : S.similarTo} · `;
  const clr = el("a", "clear-link", "show all");
  clr.href = "#";
  clr.onclick = (e) => { e.preventDefault(); S.similarTo = null; render(); };
  stats.appendChild(clr);
  box.innerHTML = "";
  ranked.forEach(({ p, s }) => box.appendChild(card(p, { score: Math.round(s * 100), why: [] })));
}
