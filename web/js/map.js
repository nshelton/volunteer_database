// Map mode: UMAP scatter of the people's profile embeddings, colored by skill
// group. Hover shows the name; click opens the detail modal.

import { el, cssVar } from "./util.js";
import { S, groupColorOf } from "./state.js";
import { openModal, renderLegendInto } from "./card.js";
import { render } from "./main.js";

let coords = null;    // id -> [x, y], each in 0..1 with y up
let layout = null;    // the in-flight / finished project() promise

async function project() {
  const { UMAP } = await import("https://cdn.jsdelivr.net/npm/umap-js@1.4.0/+esm");
  const ids = Object.keys(S.emb.vectors);
  // Seeded RNG so the layout is the same on every load.
  let seed = 42;
  const random = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  const xy = new UMAP({ nComponents: 2, nNeighbors: Math.min(15, ids.length - 1), minDist: 0.1, random })
    .fit(ids.map((id) => S.emb.vectors[id]));
  const xs = xy.map((c) => c[0]), ys = xy.map((c) => c[1]);
  const mnx = Math.min(...xs), mny = Math.min(...ys);
  const sx = (Math.max(...xs) - mnx) || 1, sy = (Math.max(...ys) - mny) || 1;
  coords = Object.fromEntries(ids.map((id, i) => [id, [(xy[i][0] - mnx) / sx, (xy[i][1] - mny) / sy]]));
}

export function renderMap() {
  renderLegendInto("map-legend");
  const box = document.getElementById("cards");
  box.innerHTML = "";
  if (!coords) {
    document.getElementById("stats").textContent = "";
    box.appendChild(el("div", "empty", "Laying out the map…"));
    // boot re-renders once the embeddings exist, which lands back here.
    if (S.emb && !layout) layout = project().then(render);
    return;
  }
  document.getElementById("stats").textContent =
    `UMAP · ${S.people.length} people · color = skill group · gray = applied, not yet a volunteer · larger dot = has publications · click to open`;
  const W = 1000, H = 640, pad = 30, R = 6, NS = "http://www.w3.org/2000/svg";
  const cDim = cssVar("--svg-dim"), cStroke = cssVar("--svg-stroke"),
        cLabel = cssVar("--svg-label"), cDimLabel = cssVar("--svg-dim-label");
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "map-svg");
  const labels = [];
  for (const p of S.people) {
    const c = coords[p.id];
    if (!c) continue;
    const cx = pad + c[0] * (W - 2 * pad), cy = pad + (1 - c[1]) * (H - 2 * pad);
    const isNew = p.status === "applied";
    const r = p.publications ? R + 2 : R;
    const op = isNew ? "0.45" : "0.8";
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("r", r);
    dot.setAttribute("fill", isNew ? cDim : groupColorOf(p)); dot.setAttribute("fill-opacity", op);
    dot.setAttribute("stroke", cStroke); dot.setAttribute("stroke-width", "1.2");
    dot.style.cursor = "pointer";
    dot.addEventListener("mouseenter", () => { dot.setAttribute("r", r + 4); dot.setAttribute("fill-opacity", "1"); });
    dot.addEventListener("mouseleave", () => { dot.setAttribute("r", r); dot.setAttribute("fill-opacity", op); });
    dot.addEventListener("click", () => openModal(p));
    svg.appendChild(dot);

    const label = document.createElementNS(NS, "text");
    label.setAttribute("x", cx); label.setAttribute("y", cy);
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("dominant-baseline", "central");
    label.setAttribute("font-size", "9");
    label.setAttribute("fill", isNew ? cDimLabel : cLabel);
    label.setAttribute("pointer-events", "none");
    label.textContent = p.name;
    labels.push(label);
  }
  for (const l of labels) svg.appendChild(l);
  box.appendChild(svg);
}
