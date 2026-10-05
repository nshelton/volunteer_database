// All shared mutable state on one object (modules mutate fields directly),
// plus app-wide constants and the taxonomy helpers that read them.

import { cssVar } from "./util.js";

export const S = {
  raw: [], tax: {}, groups: {}, people: [],
  activeCats: new Set(),
  nvOnly: false,      // browse: show only people whose status is still "applied"
  term: "",
  mode: "browse",
  emb: null,          // { vectors: { id: [floats] } } — computed in the browser after load
  semantic: true,     // semantic-search toggle (browse mode) — on by default
  // Mutable state from the bucket. The form sheet is keyed by email, and a
  // person's row in the database sheet may not have one yet, so links is the
  // hand-made join between them. See renderSignups().
  signups: { signups: [], synced_at: null },
  links: { links: {}, updated_at: null },
  showSignups: true,  // include form signups alongside the extracted profiles
  tableSort: { key: "name", dir: 1 },
  similarTo: null,    // id we're showing "find similar" results for
  activeOpp: -1,      // selected opportunity posting (match mode), -1 = none/custom
  oppText: "",        // opportunity description being matched against
};

export const LEVEL_WEIGHT = { expert: 3, proficient: 2, familiar: 1 };
// Needs that genuinely benefit from a publication record (used to weight pubs).
export const RESEARCHY = new Set(["research_academic", "machine_learning", "rendering_graphics",
  "computer_vision", "simulation_vfx", "modeling_geometry", "animation"]);
// Dummy opportunity postings for the demo. Clicking one fills the description
// box, required categories, and keywords; the description is also embedded for
// semantic ranking, so a free-text prompt works the same way.
export const OPPORTUNITIES = [
  {
    org: "Membership & Communications Committee",
    title: "Web & Data Viz Volunteer",
    text: "Seeking a volunteer to assist with web information updates and the presentation of conference submission and acceptance statistics. Needs expertise in web design and data visualisation.",
    cats: ["web_dev", "design_ux", "communication_outreach"],
    keywords: "web, visualization, statistics",
  },
  {
    org: "SIGGRAPH 2027 Conference Committee",
    title: "Courses Chair",
    text: "Seeking a Courses Chair. Must be someone with Research and Academia skills; Rendering, Computer Vision, AI and Game Development expertise; and previous SIGGRAPH volunteering roles in the conferences.",
    cats: ["research_academic", "rendering_graphics", "computer_vision", "machine_learning", "game_dev"],
    keywords: "siggraph, courses, teaching",
  },
  {
    org: "Emerging Technologies Committee",
    title: "Submission Reviewers",
    text: "Looking for people to review submissions to Emerging Technologies. We want people with any of the following skills: Haptics, Interactive Systems, XR, Display Technologies, Robotics, Human Centred Design, CAD, Scanning, 3D Reconstruction, Rendering, Simulation, Multi-Sensory Experiences.",
    cats: ["ar_vr_xr", "hardware_systems", "computer_vision", "design_ux", "rendering_graphics", "simulation_vfx", "modeling_geometry"],
    keywords: "haptics, xr, robotics, immersive",
  },
];

export const catLabel = (k) => (S.tax[k] && S.tax[k].label) || k;
export const catColor = (k) => { const g = S.tax[k] && S.tax[k].group; return (S.groups[g] && S.groups[g].color) || "#888888"; };
export const levelOf = (p, k) => { const c = (p.categories || []).find((x) => x.category === k); return c ? c.level : null; };
// Dominant taxonomy-group color for a person (used to color map points).
export function groupColorOf(p) {
  const counts = {};
  for (const c of p.categories || []) { const g = S.tax[c.category] && S.tax[c.category].group; if (g) counts[g] = (counts[g] || 0) + 1; }
  let best = null, bn = 0;
  for (const g in counts) if (counts[g] > bn) { bn = counts[g]; best = g; }
  return (best && S.groups[best]) ? S.groups[best].color : cssVar("--svg-dim");
}
