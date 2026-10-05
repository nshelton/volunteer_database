// Skills mode: force-directed category graph (ported from v1). Each circle is
// a skill category (size = people with it); links connect categories that
// share people. Click a node to list those people below.

import { el, esc, cssVar } from "./util.js";
import { S, LEVEL_WEIGHT, catLabel, catColor, levelOf } from "./state.js";
import { card, renderLegendInto } from "./card.js";

let skillsSim = null;      // live d3 force simulation
let skillsState = null;    // { nodes, links, linkG, nodeG, sub, w, h, centers }
let skillsSelected = null; // currently selected category key
let dragMoved = false;     // distinguishes a click from a drag on a node

// Leaving Skills mode: stop the live simulation.
export function stopSkills() {
  if (skillsSim) { skillsSim.stop(); skillsSim = null; skillsState = null; }
}

function buildGraphData(minLink) {
  const count = {};            // category -> # people
  const co = {};               // "a|b" -> # people with both
  for (const p of S.people) {
    const cats = [...new Set(p.categories.map((c) => c.category))];
    for (const c of cats) count[c] = (count[c] || 0) + 1;
    for (let i = 0; i < cats.length; i++)
      for (let j = i + 1; j < cats.length; j++) {
        const key = [cats[i], cats[j]].sort().join("|");
        co[key] = (co[key] || 0) + 1;
      }
  }
  const nodes = Object.keys(count).map((k) => ({
    id: k, label: catLabel(k), count: count[k],
    group: (S.tax[k] && S.tax[k].group) || "", color: catColor(k),
  }));
  const links = Object.entries(co)
    .filter(([, w]) => w >= minLink)
    .map(([k, w]) => { const [a, b] = k.split("|"); return { source: a, target: b, weight: w }; });
  return { nodes, links };
}

const ctlVal = (id) => +document.getElementById(id).value;
const clusterOn = () => document.getElementById("ctl-cluster").classList.contains("active");

// Parameter changes update the LIVE simulation (no teardown), so the graph
// eases from its current layout instead of snapping back.
export function wireSkillsControls() {
  ["ctl-charge", "ctl-link"].forEach((id) =>
    document.getElementById(id).addEventListener("input", applyForces));
  document.getElementById("ctl-cluster").onclick = (e) => {
    e.currentTarget.classList.toggle("active");
    applyForces();
  };
  // Min-link changes the link SET; update links in place, keeping node positions.
  document.getElementById("ctl-minlink").addEventListener("input", updateLinks);
}

function groupCenters(w, h) {
  const gKeys = Object.keys(S.groups);
  const centers = {};
  gKeys.forEach((g, i) => {
    const a = (i / gKeys.length) * 2 * Math.PI - Math.PI / 2;
    centers[g] = { x: w / 2 + Math.cos(a) * w * 0.27, y: h / 2 + Math.sin(a) * h * 0.33 };
  });
  return centers;
}

// Full (re)build — on entering the Skills mode.
export function renderSkillsMode() {
  const box = document.getElementById("cards");
  box.innerHTML = "";
  skillsSelected = null;
  if (skillsSim) { skillsSim.stop(); skillsSim = null; }
  if (!window.d3) {
    document.getElementById("stats").textContent = "";
    box.appendChild(el("div", "empty", "d3 failed to load — check your connection and reload."));
    return;
  }
  renderLegendInto("skills-legend");

  const w = 1000, h = 640;
  const svg = d3.create("svg").attr("viewBox", `0 0 ${w} ${h}`).attr("class", "map-svg skills-svg");
  box.appendChild(svg.node());
  const sub = el("div", "sub-cards");   // people with the selected skill
  box.appendChild(sub);

  const { nodes, links } = buildGraphData(ctlVal("ctl-minlink"));
  setSkillsStats(nodes.length, links.length);
  if (!nodes.length) { skillsState = null; return; }

  const rScale = d3.scaleSqrt().domain([1, d3.max(nodes, (d) => d.count) || 1]).range([9, 46]);
  nodes.forEach((n) => (n.r = rScale(n.count)));

  const linkG = svg.append("g").attr("stroke", cssVar("--svg-link")).attr("stroke-opacity", 0.6);
  const nodeG = svg.append("g");
  skillsState = { w, h, nodes, links, linkG, nodeG, sub, centers: groupCenters(w, h) };

  skillsSim = d3.forceSimulation(nodes)
    .force("charge", d3.forceManyBody())
    .force("link", d3.forceLink(links).id((d) => d.id).distance(100))
    .force("x", d3.forceX(w / 2))
    .force("y", d3.forceY(h / 2))
    .force("collide", d3.forceCollide((d) => d.r + 3))
    .on("tick", tickSkills);

  drawSkillLinks();
  drawSkillNodes();
  applyForces();   // strengths + clustering from current control values
}

function drawSkillNodes() {
  const sel = skillsState.nodeG.selectAll("g.node").data(skillsState.nodes, (d) => d.id);
  sel.exit().remove();
  const ent = sel.enter().append("g").attr("class", "node").style("cursor", "pointer")
    .call(dragBehavior())
    .on("click", (e, d) => { if (!dragMoved) selectSkill(d.id); });
  ent.append("circle").attr("r", (d) => d.r).attr("fill", (d) => d.color)
    .attr("stroke", cssVar("--svg-stroke")).attr("stroke-width", 1.5);
  ent.append("text").text((d) => d.label).attr("text-anchor", "middle")
    .attr("dominant-baseline", "central").attr("pointer-events", "none");
  ent.append("title").text((d) => `${d.label}: ${d.count} people`);
}

function drawSkillLinks() {
  const wScale = d3.scaleLinear().domain([1, d3.max(skillsState.links, (d) => d.weight) || 1]).range([0.6, 6]);
  const sel = skillsState.linkG.selectAll("line").data(skillsState.links,
    (d) => `${d.source.id || d.source}|${d.target.id || d.target}`);
  sel.exit().remove();
  sel.enter().append("line").merge(sel).attr("stroke-width", (d) => wScale(d.weight));
}

function tickSkills() {
  if (!skillsState) return;
  skillsState.linkG.selectAll("line")
    .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
    .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
  skillsState.nodeG.selectAll("g.node").attr("transform", (d) => `translate(${d.x},${d.y})`);
}

// Update force strengths + clustering on the live sim, then gently re-heat.
function applyForces() {
  if (!skillsSim || !skillsState) return;
  const cluster = clusterOn();
  const { w, h, centers } = skillsState;
  skillsSim.force("charge").strength(-ctlVal("ctl-charge"));
  skillsSim.force("link").strength((d) => (ctlVal("ctl-link") / 100) * Math.min(1, d.weight / 3));
  skillsSim.force("x").x((d) => (cluster && centers[d.group] ? centers[d.group].x : w / 2)).strength(cluster ? 0.25 : 0.05);
  skillsSim.force("y").y((d) => (cluster && centers[d.group] ? centers[d.group].y : h / 2)).strength(cluster ? 0.25 : 0.05);
  skillsSim.alpha(0.3).restart();
}

// Min-link changed: recompute links against the SAME node objects so positions
// persist, swap them into the link force, redraw, and gently re-heat.
function updateLinks() {
  if (!skillsSim || !skillsState) return;
  const byId = new Map(skillsState.nodes.map((n) => [n.id, n]));
  const links = buildGraphData(ctlVal("ctl-minlink")).links
    .map((l) => ({ source: byId.get(l.source), target: byId.get(l.target), weight: l.weight }))
    .filter((l) => l.source && l.target);
  skillsState.links = links;
  skillsSim.force("link").links(links);
  drawSkillLinks();
  if (!skillsSelected) setSkillsStats(skillsState.nodes.length, links.length);
  skillsSim.alpha(0.3).restart();
}

function setSkillsStats(nNodes, nLinks) {
  document.getElementById("stats").textContent =
    `${nNodes} skill categories · ${nLinks} connections · node size = people, links = shared people · click a category to list its people`;
}

function dragBehavior() {
  return d3.drag()
    .on("start", (e, d) => { dragMoved = false; if (!e.active) skillsSim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on("drag", (e, d) => { dragMoved = true; d.fx = e.x; d.fy = e.y; })
    .on("end", (e, d) => { if (!e.active) skillsSim.alphaTarget(0); d.fx = null; d.fy = null; });
}

// Click a skill node -> cards for everyone with that skill below the graph,
// ranked by their level in it (expert > proficient > familiar).
function selectSkill(catKey) {
  if (!skillsState) return;
  skillsSelected = catKey;
  const cSel = cssVar("--svg-selected"), cStroke = cssVar("--svg-stroke");
  skillsState.nodeG.selectAll("g.node circle")
    .attr("stroke", (d) => (d.id === catKey ? cSel : cStroke))
    .attr("stroke-width", (d) => (d.id === catKey ? 3 : 1.5));

  const people = S.people
    .map((p) => ({ p, lvl: levelOf(p, catKey) }))
    .filter((x) => x.lvl)
    .sort((a, b) => (LEVEL_WEIGHT[b.lvl] - LEVEL_WEIGHT[a.lvl]) || a.p.name.localeCompare(b.p.name));

  const stats = document.getElementById("stats");
  stats.textContent = `${catLabel(catKey)} · ${people.length} people · `;
  const clr = el("a", "clear-link", "clear selection");
  clr.href = "#";
  clr.onclick = (e) => { e.preventDefault(); clearSkillSelection(); };
  stats.appendChild(clr);

  const sub = skillsState.sub;
  sub.innerHTML = "";
  people.forEach(({ p, lvl }) => {
    const c = card(p);
    c.appendChild(el("p", "why", "▸ " + esc(lvl)));
    sub.appendChild(c);
  });
  if (!people.length) sub.appendChild(el("div", "empty", "No one has this category."));
}

function clearSkillSelection() {
  skillsSelected = null;
  if (!skillsState) return;
  skillsState.sub.innerHTML = "";
  skillsState.nodeG.selectAll("g.node circle").attr("stroke", cssVar("--svg-stroke")).attr("stroke-width", 1.5);
  setSkillsStats(skillsState.nodes.length, skillsState.links.length);
}
