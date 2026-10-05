// Load the volunteer database from its Google Sheet and shape the person
// records the views render.

import { authedFetch, sheetToken, dropSheetToken, dbSheetId } from "../auth.js";
import { S } from "./state.js";

// The sheet is the database. People is hand-edited (one row per person, `id`
// is the key); Profiles, Categories and Publications are written by the
// extraction tooling and join to it by `id`.
const TABS = ["People", "Profiles", "Categories", "Publications"];

// One tab's values (header row, then rows of strings with trailing blanks
// trimmed off by the API) -> [{ header: cell }], skipping rows with no id.
function rows(values) {
  const [head, ...body] = values;
  return body.map((r) => Object.fromEntries(head.map((h, i) => [h, (r[i] || "").trim()]))).filter((r) => r.id);
}
const list = (s) => (s || "").split(";").map((x) => x.trim()).filter(Boolean);
function byId(rs) {
  const m = new Map();
  for (const r of rs) { if (!m.has(r.id)) m.set(r.id, []); m.get(r.id).push(r); }
  return m;
}

// Read with the signed-in user's own Google access, so who can see the data is
// decided by who the sheet is shared with.
async function readSheet() {
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${dbSheetId()}/values:batchGet?`
    + TABS.map((t) => "ranges=" + t).join("&");
  const r = await fetch(url, { headers: { Authorization: "Bearer " + await sheetToken() } });
  if (r.status === 401) { dropSheetToken(); throw new Error("Google access expired. Open the sheet again."); }
  if (r.status === 403 || r.status === 404) throw new Error("Your Google account can't open the volunteer sheet. Ask for it to be shared with you.");
  if (!r.ok) throw new Error(`Couldn't read the volunteer sheet (${r.status}).`);
  return (await r.json()).valueRanges.map((v) => rows(v.values));
}

export function shapePeople([people, profiles, categories, publications]) {
  const prof = new Map(profiles.map((r) => [r.id, r]));
  const cats = byId(categories), works = byId(publications);
  return people.map((row) => {
    const ex = prof.get(row.id) || {};
    return {
      id: row.id, url: row.source_url, section: row.group, source_type: row.source_type,
      name: row.name || "Unknown", email: row.email.toLowerCase(), status: row.status, notes: row.notes,
      headline: ex.headline || "", summary: ex.summary || "",
      location: ex.location || "", seniority: ex.seniority || "",
      categories: (cats.get(row.id) || []).map((c) => ({ category: c.category, level: c.level, evidence: c.evidence })),
      skills: list(ex.skills), tools: list(ex.tools), roles: list(ex.roles), education: list(ex.education),
      themes: list(ex.themes),
      publications: ex.openalex_url
        ? { openalex_url: ex.openalex_url, orcid: ex.orcid, works_count: +ex.works_count, works: works.get(row.id) || [] }
        : null,
    };
  });
}

export async function loadData() {
  const [sheet, tax] = await Promise.all([
    readSheet(),
    authedFetch("data/taxonomy.json").then((r) => r.json()),
  ]);
  // Absent on a local static preview (no backend) and on a fresh bucket.
  S.signups = await authedFetch("data/signups.json").then((r) => r.json()).catch(() => S.signups);
  S.links = await authedFetch("data/links.json").then((r) => r.json()).catch(() => S.links);
  S.tax = tax.categories;
  S.groups = tax.groups;
  S.raw = shapePeople(sheet);
  rebuildPeople();
}

// A signup with no volunteer record still deserves a card: we know they raised
// a hand and what they want, just nothing about their skills. Their program
// interests stand in for themes so the card isn't empty. Long free-text
// write-ins are dropped from the chip list — they read as notes, not tags.
const splitList = (s) => (s || "").split(",").map((x) => x.trim()).filter((x) => x && x.length <= 44);

function signupPerson(s) {
  return {
    id: "signup:" + s.email,
    url: "", section: "signup", source_type: "form",
    name: s.email,
    headline: [s.conferences, s.is_new === "No" ? "volunteered before" : "new volunteer"].filter(Boolean).join(" · "),
    summary: s.notes || "",
    location: "", seniority: "",
    categories: [], skills: [], tools: [], roles: [], education: [],
    themes: splitList(s.programs).slice(0, 8),
    publications: null,
    signup: s,
  };
}

// Browse order is shuffled once per person and kept stable, so re-linking a
// signup doesn't reshuffle the whole grid under you.
const RAND = new Map();
const randFor = (id) => { if (!RAND.has(id)) RAND.set(id, Math.random()); return RAND.get(id); };

// S.people = the sheet's people, each carrying its signup if one has been
// linked (by hand, or because the sheet's email matches the form's), plus a
// synthetic entry per unlinked signup. Rebuilt whenever a link
// changes, so the grid reflects a new association immediately.
export function rebuildPeople() {
  S.people = S.raw.map((p) => ({ ...p }));
  const people = new Map(S.people.map((p) => [p.id, p]));
  const rows = S.signups.signups || [];
  const linked = new Set();
  for (const [email, l] of Object.entries(S.links.links || {})) {
    const p = people.get(l.volunteer_id);
    const rec = rows.find((s) => s.email === email);
    if (!p || !rec) continue;
    p.signup = rec;
    linked.add(email);
  }
  for (const p of S.people) {
    const rec = !p.signup && p.email && rows.find((s) => s.email === p.email);
    if (rec) { p.signup = rec; linked.add(p.email); }
  }
  for (const s of rows) if (!linked.has(s.email)) S.people.push(signupPerson(s));
  S.people.forEach((p) => { p._rand = randFor(p.id); });
}

export const isSignupOnly = (p) => p.section === "signup";
export const visiblePeople = () => (S.showSignups ? S.people : S.people.filter((p) => !isSignupOnly(p)));
export const emailOf = (p) => p.email || (p.signup ? p.signup.email : "");

export function matchesSearch(p) {
  if (!S.term) return true;
  const s = p.signup;
  const hay = [p.name, p.headline, p.summary, p.skills.join(" "), p.tools.join(" "), p.roles.join(" "), p.themes.join(" "),
    s ? [s.email, s.committees, s.programs, s.notes].join(" ") : ""].join(" ").toLowerCase();
  return hay.includes(S.term);
}
