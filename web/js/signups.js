// Signups mode: form responses + the hand-made join. The form sheet says who
// raised their hand and what they're interested in. It is keyed by email and
// carries no name, resume URL or skills. volunteers.json is keyed by a URL
// slug and carries no email. Nothing joins the two automatically, so this view
// lets any signed-in user assert "this signup is that person"; the mapping
// lives in the bucket and is shared by everyone.

import { authedPost, sheetToken, sheetId } from "../auth.js";
import { el, esc, extLink, relTime } from "./util.js";
import { S } from "./state.js";
import { rebuildPeople } from "./data.js";
import { openModal } from "./card.js";

const sheetUrl = (id) => `https://docs.google.com/spreadsheets/d/${id}/edit`;
const QUICK_LINK_MIN = 0.85;   // score needed to offer a one-click link
const letters = (s) => (s || "").toLowerCase().replace(/[^a-z]+/g, "");
const words = (s) => (s || "").toLowerCase().replace(/[^a-z]+/g, " ").trim().split(/\s+/).filter(Boolean);

// Email local-parts track names and resume URLs surprisingly well
// (jdoe0129@ -> jdoe0129.github.io, jane.doe@ -> Jane Ann Doe), so a cheap
// string match floats the likely record to the top of the
// dropdown. It only ever suggests — a human still confirms.
function suggestFor(email) {
  const local = letters(email.split("@")[0]);
  if (!local) return [];
  return S.people.map((p) => {
    const toks = words(p.name).filter((t) => t.length > 2);
    const flat = toks.join("");
    let s = 0;
    if (flat && flat === local) s = 1;
    else if (toks.length) s = 0.9 * toks.filter((t) => local.includes(t)).length / toks.length;
    if (local.length > 3 && letters(p.url).includes(local)) s = Math.max(s, 0.85);
    return { p, s };
  }).filter((x) => x.s > 0.35).sort((a, b) => b.s - a.s).slice(0, 4);
}

export function renderSignups() {
  const box = document.getElementById("cards");
  box.innerHTML = "";
  document.getElementById("stats").textContent = "";

  const rows = S.signups.signups || [];
  const links = S.links.links || {};
  const byId = new Map(S.people.map((p) => [p.id, p]));
  box.appendChild(diagnostics(rows, links));

  if (!rows.length) {
    box.appendChild(el("div", "empty", "No signups synced yet — hit “Sync sheet” to pull the form responses."));
    return;
  }
  const list = el("div", "signup-list");
  // Unlinked first: those are the ones still waiting on a human decision.
  [...rows].sort((a, b) => (links[a.email] ? 1 : 0) - (links[b.email] ? 1 : 0))
    .forEach((r) => list.appendChild(signupRow(r, links, byId)));
  box.appendChild(list);
}

function diagnostics(rows, links) {
  const d = el("div", "diag");
  const nLinked = Object.keys(links).length;
  const linkedIds = new Set(Object.values(links).map((l) => l.volunteer_id));

  const facts = el("div", "diag-facts");
  facts.appendChild(el("div", "diag-line",
    `<b>${rows.length}</b> signups · <b>${nLinked}</b> linked · <b>${Math.max(0, rows.length - nLinked)}</b> to review`));
  facts.appendChild(el("div", "diag-sub", esc(
    `${S.people.length - linkedIds.size} of ${S.people.length} volunteer records have no signup · ` +
    `synced ${relTime(S.signups.synced_at)}` + (S.signups.synced_by ? ` by ${S.signups.synced_by}` : "") +
    (S.signups.row_count ? ` · ${S.signups.row_count} sheet rows` : ""))));
  d.appendChild(facts);

  const actions = el("div", "diag-actions");
  const sync = el("button", "sync-btn", "Sync sheet");
  sync.onclick = () => syncSheet(sync);
  actions.appendChild(sync);
  const id = S.signups.sheet_id || sheetId();
  if (id) actions.appendChild(extLink(sheetUrl(id), "open sheet ↗"));
  d.appendChild(actions);

  const msg = el("div", "diag-msg hidden");
  msg.id = "diag-msg";
  d.appendChild(msg);
  return d;
}

function diagSay(text, bad) {
  const msg = document.getElementById("diag-msg");
  if (!msg) return;
  msg.textContent = text;
  msg.classList.remove("hidden");
  msg.classList.toggle("bad", !!bad);
}

// Read the sheet with the signed-in user's OWN Google access token (the sheet
// belongs to someone else, so the server has no credentials for it), then hand
// the rows to the server to persist for every other user.
async function syncSheet(btn) {
  const id = S.signups.sheet_id || sheetId();
  if (!id) return diagSay("No SHEET_ID configured on the server.", true);
  btn.disabled = true;
  btn.textContent = "Syncing…";
  try {
    const token = await sheetToken();
    const r = await fetch(`https://sheets.googleapis.com/v4/spreadsheets/${id}/values/A:J`,
      { headers: { Authorization: "Bearer " + token } });
    if (r.status === 403 || r.status === 404) throw new Error("your Google account can't read that sheet");
    if (!r.ok) throw new Error("sheet read failed (" + r.status + ")");
    const res = await authedPost("api/signups", { values: (await r.json()).values || [] });
    if (!res.ok) throw new Error("save failed (" + res.status + ")");
    S.signups = await res.json();
    rebuildPeople();
    renderSignups();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Sync sheet";
    diagSay("Sync failed — " + e.message, true);
  }
}

function signupRow(r, links, byId) {
  const row = el("div", "signup");
  const linked = links[r.email];
  if (linked) row.classList.add("is-linked");

  const head = el("div", "signup-head");
  head.appendChild(el("span", "signup-email", esc(r.email)));
  if (r.timestamp) head.appendChild(el("span", "signup-when", esc(r.timestamp.split(" ")[0])));
  row.appendChild(head);

  const facts = [];
  if (r.conferences) facts.push(r.conferences);
  if (r.membership && !/^n\/?a$/i.test(r.membership)) facts.push("ACM " + r.membership);
  if (facts.length) row.appendChild(el("p", "signup-facts", esc(facts.join(" · "))));
  if (r.committees) row.appendChild(el("p", "signup-detail", "<b>Committees:</b> " + esc(r.committees)));
  if (r.programs) row.appendChild(el("p", "signup-detail", "<b>Programs:</b> " + esc(r.programs)));
  if (r.notes) row.appendChild(el("p", "signup-notes", esc(r.notes)));

  row.appendChild(linkControl(r, linked, byId));
  return row;
}

function linkControl(r, linked, byId) {
  const wrap = el("div", "signup-link");
  const sel = el("select", "link-select");
  sel.appendChild(new Option("— not linked —", ""));

  const suggestions = suggestFor(r.email);
  if (suggestions.length) {
    const g = document.createElement("optgroup");
    g.label = "Suggested";
    suggestions.forEach(({ p }) => g.appendChild(new Option(p.name, p.id)));
    sel.appendChild(g);
  }
  const all = document.createElement("optgroup");
  all.label = "All volunteers";
  [...S.people].sort((a, b) => a.name.localeCompare(b.name))
    .forEach((p) => all.appendChild(new Option(p.name, p.id)));
  sel.appendChild(all);

  sel.value = linked ? linked.volunteer_id : "";
  sel.onchange = () => setLink(r.email, sel.value, sel);
  wrap.appendChild(sel);

  if (linked) {
    const who = byId.get(linked.volunteer_id);
    wrap.appendChild(el("span", "link-note",
      `✓ ${esc(who ? who.name : linked.volunteer_id)} · by ${esc(linked.by || "?")}`));
    if (who) {
      const open = el("button", "link-open", "open");
      open.onclick = () => openModal(who);
      wrap.appendChild(open);
    }
  } else if (suggestions.length && suggestions[0].s >= QUICK_LINK_MIN) {
    // Only offer the one-click shortcut when the match is near-certain. Weaker
    // hits stay in the dropdown: a substring can lie (an address can "contain"
    // someone else's short surname), and a wrong link is worse than a second click.
    const top = suggestions[0].p;
    const quick = el("button", "link-quick", `link → ${esc(top.name)}`);
    quick.onclick = () => setLink(r.email, top.id, sel);
    wrap.appendChild(quick);
  }
  return wrap;
}

async function setLink(email, volunteerId, sel) {
  sel.disabled = true;
  try {
    const res = await authedPost("api/link", { email, volunteer_id: volunteerId });
    if (!res.ok) throw new Error(res.status);
    S.links = await res.json();
    rebuildPeople();   // the signup folds into its volunteer's card, or back out
    renderSignups();
  } catch (_) {
    sel.disabled = false;
    diagSay("Couldn't save that link — try again.", true);
  }
}
