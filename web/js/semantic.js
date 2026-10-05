// In-browser embedding: the people's profiles (for semantic search, "find
// similar" and the map) and the queries they are ranked against. One model for
// both, so query·profile cosine is a dot product.

import { S } from "./state.js";

const MODEL = "Xenova/all-MiniLM-L6-v2";
let extractor = null;         // lazy transformers.js embedding pipeline
const OPP_VECS = new Map();   // description -> embedding promise (embed once)

async function getExtractor() {
  if (extractor) return extractor;
  const mod = await import("https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2");
  mod.env.allowLocalModels = false;
  extractor = await mod.pipeline("feature-extraction", MODEL);
  return extractor;
}

export async function embedQuery(text) {
  const out = await (await getExtractor())(text, { pooling: "mean", normalize: true });
  return Array.from(out.data);
}

export function oppVec(text) {
  if (!OPP_VECS.has(text))
    OPP_VECS.set(text, embedQuery(text).catch((e) => { OPP_VECS.delete(text); throw e; }));
  return OPP_VECS.get(text);
}

// Lead with the curated themes: they are higher quality than the scraped
// prose, and all-MiniLM truncates at ~256 tokens, so order matters.
function profileText(p) {
  return [
    p.name, p.themes.join(". "), p.headline, p.summary,
    p.skills.join(", "), p.tools.join(", "), p.roles.join(", "),
    (p.publications ? p.publications.works.map((w) => w.title) : []).join(". "),
  ].filter(Boolean).join(". ").slice(0, 3000);
}

function hash(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = (h * 33 ^ s.charCodeAt(i)) >>> 0;
  return h;
}

// Fill S.emb with a vector per person. The sheet can change under us at any
// time, so nothing is precomputed: each vector is cached in this browser
// against a hash of the text it came from, and only new or edited profiles are
// re-embedded on the next load.
export async function embedProfiles() {
  const cache = JSON.parse(localStorage.getItem("emb") || "{}");   // id -> { h, v }
  const vectors = {}, keep = {};
  for (const p of S.raw) {
    const text = profileText(p), h = hash(text), hit = cache[p.id];
    const v = hit && hit.h === h ? hit.v : (await embedQuery(text)).map((x) => Math.round(x * 1e4) / 1e4);
    vectors[p.id] = v;
    keep[p.id] = { h, v };
  }
  S.emb = { vectors };
  localStorage.setItem("emb", JSON.stringify(keep));
}
