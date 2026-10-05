// Shared UI pieces: the compact person card, the detail modal, and the
// skill-group legend used by the Map and Skills views.

import { el, esc, decode, extLink } from "./util.js";
import { S, catLabel, catColor } from "./state.js";
import { isSignupOnly } from "./data.js";
import { render } from "./main.js";

// Compact card: name, one-line headline, up to 3 themes and 3 categories with
// "+N" overflow hints, and a single publications line. Everything else
// (skills, tools, paper titles, evidence) lives in the modal.
export function card(p, match) {
  const c = el("div", "card");
  if (p.status === "applied") c.classList.add("new-volunteer");  // not yet volunteered
  if (isSignupOnly(p)) c.classList.add("signup-card");                  // form response, no profile
  const head = el("div", "card-head");
  head.appendChild(el("h3", "card-name", esc(p.name)));
  head.appendChild(match
    ? el("span", "score", "▸ " + match.score.toFixed(0))
    : el("span", "src-tag", esc(p.source_type || p.section || "")));
  c.appendChild(head);
  if (p.signup && !isSignupOnly(p)) c.appendChild(el("span", "signed-up", "✓ signed up"));
  if (match && match.why.length) c.appendChild(el("p", "why", "✓ " + esc([...new Set(match.why)].join(", "))));
  else if (p.headline) c.appendChild(el("p", "card-headline", esc(p.headline)));
  if (p.themes.length) {
    const tl = el("div", "theme-list");
    p.themes.slice(0, 2).forEach((h) => tl.appendChild(el("span", "theme", esc(h))));
    if (p.themes.length > 2) tl.appendChild(el("span", "more", `+${p.themes.length - 2}`));
    c.appendChild(tl);
  }
  if (p.categories.length) {
    const row = el("div", "cat-row");
    p.categories.slice(0, 3).forEach((ct) => {
      const chip = el("span", "chip", esc(catLabel(ct.category)));
      chip.style.setProperty("--c", catColor(ct.category));
      row.appendChild(chip);
    });
    if (p.categories.length > 3) row.appendChild(el("span", "more", `+${p.categories.length - 3}`));
    c.appendChild(row);
  }
  if (p.publications) {
    const pub = p.publications;
    const links = el("div", "pub-links");
    links.appendChild(el("span", "pub-icon", "&#128196;"));
    links.appendChild(extLink(pub.openalex_url, `${pub.works_count} works · OpenAlex`));
    if (pub.orcid) links.appendChild(extLink(pub.orcid, "ORCID"));
    c.appendChild(links);
  }
  c.onclick = () => openModal(p);
  return c;
}

export function openModal(p) {
  const cats = p.categories.map((c) =>
    `<div class="cat-line"><span class="chip" style="--c:${catColor(c.category)}">${esc(catLabel(c.category))} · ${esc(c.level || "")}</span></div>` +
    (c.evidence ? `<p class="evidence">${esc(c.evidence)}</p>` : "")
  ).join("");
  // Signup-only people borrow `themes` to display their program interests,
  // which the signup section already lists in full — don't print them twice.
  const themes = p.themes.length && !isSignupOnly(p)
    ? `<section><h3>Themes · gdrive</h3><div class="theme-list">${p.themes.map((h) => `<span class="theme">${esc(h)}</span>`).join("")}</div></section>`
    : "";
  const pub = p.publications;
  const pubs = pub
    ? `<section><h3>Publications</h3>
        <p>${pub.works_count} works · <a href="${esc(pub.openalex_url)}" target="_blank" rel="noopener">OpenAlex</a>${pub.orcid ? ` · <a href="${esc(pub.orcid)}" target="_blank" rel="noopener">ORCID</a>` : ""}</p>
        ${(pub.works || []).map((w) => `<p class="evidence"><b>${esc(decode(w.title))}</b>${w.venue ? " — " + esc(decode(w.venue)) : ""}${w.year ? ` (${w.year})` : ""}${w.doi ? ` · <a href="${esc(w.doi)}" target="_blank" rel="noopener">doi</a>` : ""}</p>`).join("")}
       </section>`
    : "";
  const s = p.signup;
  const row = (label, v) => (v ? `<p class="evidence"><b>${label}:</b> ${esc(v)}</p>` : "");
  const signup = s
    ? `<section><h3>Volunteer signup</h3>
        ${row("Email", s.email)}${row("Submitted", s.timestamp)}
        ${row("Conference", s.conferences)}${row("Programs", s.programs)}
        ${row("Committees", s.committees)}
        ${s.membership && !/^n\/?a$/i.test(s.membership) ? row("ACM member", s.membership) : ""}
        ${row("Volunteered before", s.past_experience)}${row("Notes", s.notes)}
       </section>`
    : "";
  const canSim = S.emb && S.emb.vectors[p.id];
  document.getElementById("modal-body").innerHTML = `
    <h2>${esc(p.name)}</h2>
    <p class="sub">${esc(p.headline || "")}${p.location ? " · " + esc(p.location) : ""}${p.seniority ? " · " + esc(p.seniority) : ""}</p>
    ${canSim ? '<button id="find-similar" class="similar-btn">⤳ Find similar people</button>' : ""}
    ${signup}
    ${themes}
    ${pubs}
    ${p.summary ? `<section><h3>Summary</h3><p class="evidence">${esc(p.summary)}</p></section>` : ""}
    ${cats ? `<section><h3>Skill categories</h3>${cats}</section>` : ""}
    ${p.skills.length ? `<section><h3>Skills</h3><div class="skill-row">${p.skills.map((s) => `<span class="skill">${esc(s)}</span>`).join("")}</div></section>` : ""}
    ${p.tools.length ? `<section><h3>Tools</h3><div class="skill-row">${p.tools.map((s) => `<span class="skill">${esc(s)}</span>`).join("")}</div></section>` : ""}
    ${p.roles.length ? `<section><h3>Roles</h3><div class="skill-row">${p.roles.map((s) => `<span class="skill">${esc(s)}</span>`).join("")}</div></section>` : ""}
    ${p.education.length ? `<section><h3>Education</h3>${p.education.map((s) => `<p class="evidence">${esc(s)}</p>`).join("")}</section>` : ""}
    <section><h3>Source</h3><p>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a>` : "—"} <span class="evidence">(${esc(p.source_type || "")}${p.section ? " · " + esc(p.section) : ""})</span></p></section>
  `;
  if (canSim) document.getElementById("find-similar").onclick = () => {
    S.similarTo = p.id; S.mode = "browse"; S.semantic = false;
    document.getElementById("semantic").classList.remove("active");
    document.getElementById("mode-browse").classList.add("active");
    document.getElementById("mode-match").classList.remove("active");
    document.getElementById("mode-skills").classList.remove("active");
    document.getElementById("match-controls").classList.add("hidden");
    document.getElementById("modal").classList.add("hidden");
    render();
  };
  document.getElementById("modal").classList.remove("hidden");
}

export function renderLegendInto(id) {
  const box = document.getElementById(id);
  box.innerHTML = "";
  Object.values(S.groups).forEach((g) => {
    box.appendChild(el("div", "legend-item", `<span class="legend-dot" style="background:${g.color}"></span>${esc(g.label)}`));
  });
}
