// The two Google grants the site runs on. An ID token says who the user is, so
// the server can check its allowlist before serving /data/* and /api/* (skipped
// on local / LAN hosts, which have no backend). An OAuth access token lets the
// browser read Google Sheets as that user: the volunteer database itself, and
// the form-responses sheet. Exports authedFetch(), authedPost(), sheetToken(),
// dropSheetToken(), sheetId(), dbSheetId() + runWithAuth().

let ID_TOKEN = null;
let EMAIL = "";           // from the ID token; preselects the account for the sheet grant
let CONFIG = { client_id: "", sheet_id: "", db_sheet_id: "" };
let SHEET_TOKEN = null;   // { token, expires } — OAuth access token for the Sheets reads

export const sheetId = () => CONFIG.sheet_id;        // form responses
export const dbSheetId = () => CONFIG.db_sheet_id;   // the volunteer database

// Attaches the Google ID token so the server can authorize /data/* requests.
export function authedFetch(url) {
  return fetch(url, { headers: ID_TOKEN ? { Authorization: "Bearer " + ID_TOKEN } : {} });
}

export function authedPost(url, body) {
  return fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(ID_TOKEN ? { Authorization: "Bearer " + ID_TOKEN } : {}),
    },
    body: JSON.stringify(body),
  });
}

// The sheets are read with the signed-in user's own access rather than a
// service account, so sharing a sheet is what grants someone the data. That
// takes a separate OAuth access token, scoped to reading sheets. It is kept
// for the tab's lifetime so a reload doesn't raise the Google popup again.
export function sheetToken() {
  if (!SHEET_TOKEN) SHEET_TOKEN = JSON.parse(sessionStorage.getItem("sheet_token") || "null");
  if (SHEET_TOKEN && Date.now() < SHEET_TOKEN.expires) return Promise.resolve(SHEET_TOKEN.token);
  return new Promise((resolve, reject) => {
    const client = google.accounts.oauth2.initTokenClient({
      client_id: CONFIG.client_id,
      scope: "https://www.googleapis.com/auth/spreadsheets.readonly",
      prompt: "",            // no consent screen once it has been granted
      login_hint: EMAIL,
      callback: (resp) => {
        if (!resp || !resp.access_token) return reject(new Error("no-token"));
        // Renew a minute early rather than discover expiry mid-request.
        SHEET_TOKEN = { token: resp.access_token, expires: Date.now() + (resp.expires_in - 60) * 1000 };
        sessionStorage.setItem("sheet_token", JSON.stringify(SHEET_TOKEN));
        resolve(resp.access_token);
      },
      error_callback: (err) => reject(new Error((err && err.type) || "token-denied")),
    });
    client.requestAccessToken();
  });
}

export function dropSheetToken() {
  SHEET_TOKEN = null;
  sessionStorage.removeItem("sheet_token");
}

function _waitForGoogle(timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    (function check() {
      if (window.google && google.accounts && google.accounts.id) return resolve();
      if (Date.now() - start > timeoutMs) return reject(new Error("gsi-timeout"));
      setTimeout(check, 100);
    })();
  });
}

// Local / LAN preview (localhost, *.local, private IPs) has no auth backend, so
// skip the allowlist check there. Cloud Run is a public *.run.app host → always
// gated.
function _isLocalDev() {
  const h = location.hostname;
  return ["localhost", "127.0.0.1", "[::1]", ""].includes(h)
    || h.endsWith(".local")
    || /^(10\.|127\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h);
}

// Tag the GA session with a pseudonymous per-user key: the first 12 hex chars
// of SHA-256(email). GA's terms forbid sending the email itself. Map a key back
// to a person with:  echo -n "their@email.com" | shasum -a 256 | cut -c1-12
async function _trackLogin() {
  if (typeof gtag !== "function") return;
  let key = "unknown";
  try {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(EMAIL));
    key = [...new Uint8Array(buf)].slice(0, 6).map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch (_) {}
  gtag("set", { user_id: key });
  gtag("set", "user_properties", { user_key: key });
  gtag("event", "login", { method: "Google" });
}

function _gateError(msg) {
  const e = document.getElementById("login-error");
  if (e) { e.textContent = msg; e.classList.remove("hidden"); }
}

// Get read access to the sheets, then run `boot` and drop the gate. Asked for
// straight away, but a browser may block Google's popup when it isn't the
// direct result of a click, and the user may not have the sheet shared with
// them; either way the gate stays up with a button to try again.
async function _openSheet(boot) {
  const btn = document.getElementById("sheet-btn"), err = document.getElementById("login-error");
  document.getElementById("gbtn").classList.add("hidden");
  btn.classList.add("hidden");
  err.classList.add("hidden");
  try {
    await sheetToken();
    await boot();
    document.getElementById("login-gate").classList.add("hidden");
  } catch (e) {
    // Our own errors are sentences; Google's are codes like popup_closed.
    _gateError(e.message.includes(" ") ? e.message : "Allow read access to Google Sheets to load the volunteer database.");
    btn.classList.remove("hidden");
    btn.onclick = () => _openSheet(boot);
  }
}

// Run `boot` once a valid, allowlisted Google account signs in (the allowlist
// is skipped on a local host) and can read the volunteer sheet.
export async function runWithAuth(boot) {
  try { CONFIG = await fetch("auth-config.json").then((r) => r.json()); } catch (_) {}
  if (!CONFIG.client_id) return _gateError(_isLocalDev()
    ? "Local preview needs web/auth-config.json (see CLAUDE.md)."
    : "Sign-in is not configured yet. Try again shortly.");

  try { await _waitForGoogle(); }
  catch (_) { return _gateError("Couldn't load Google Sign-In. Disable blockers and reload."); }

  if (_isLocalDev()) return _openSheet(boot);

  google.accounts.id.initialize({
    client_id: CONFIG.client_id,
    callback: async (resp) => {
      ID_TOKEN = resp.credential;
      const r = await authedFetch("data/taxonomy.json"); // probe the allowlist
      if (r.status === 200) {
        EMAIL = (JSON.parse(atob(ID_TOKEN.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).email || "").toLowerCase();
        _trackLogin();
        _openSheet(boot);
      }
      else if (r.status === 403) { ID_TOKEN = null; _gateError("That account isn't authorized for this site."); }
      else { ID_TOKEN = null; _gateError("Sign-in failed (" + r.status + "). Please try again."); }
    },
  });
  google.accounts.id.renderButton(document.getElementById("gbtn"),
    { theme: "outline", size: "large", text: "signin_with", shape: "pill" });
  google.accounts.id.prompt(); // also show One Tap
}
