"use strict";

const $ = (s) => document.querySelector(s);
const logEl = $("#log");

const ROLES = {
  "ise1":     "Cisco ISE 3.4 — policy / admin node",
  "dc-demo":  "Windows Server — DNS · NTP · AD · CA",
  "wlc-demo": "Cisco 9800-CL — wireless LAN controller",
  "nad-sw":   "Cisco Catalyst 9000v — wired 802.1X switch (NAD)",
  "paloalto": "Palo Alto VM-Series — next-gen firewall",
  "veos":     "Arista vEOS — data-center switch",
  "arubacx":  "Aruba CX — switch",
  "jumpbox":  "Linux desktop — the jump host you drive (resets with the lab)",
};

function log(msg, cls) {
  const t = new Date().toLocaleTimeString([], { hour12: false });
  const line = document.createElement("span");
  if (cls) line.className = cls;
  line.textContent = `[${t}] ${msg}\n`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) {
    const err = new Error((data && data.detail) || `HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return data;
}

function renderVMs(vms) {
  const wrap = $("#vms");
  wrap.innerHTML = "";
  for (const vm of vms) {
    const running = vm.status === "running";
    const el = document.createElement("div");
    el.className = "vm";
    el.innerHTML = `
      <div class="name">${vm.name}</div>
      <div class="role">${ROLES[vm.name] || ""}</div>
      <div class="meta">
        <span class="pill ${running ? "running" : "stopped"}">${vm.status || "unknown"}</span>
        <span class="pill ${vm.golden ? "golden-ok" : "golden-no"}">${vm.golden ? "golden ✓" : "no golden"}</span>
      </div>`;
    wrap.appendChild(el);
  }
}

function applyMaintenance(result) {
  const banner = $("#maintBanner");
  const btn = $("#resetBtn");
  if (result.maintenance) {
    banner.hidden = false;
    banner.textContent =
      "⚠ The lab is temporarily offline — a reset didn't come back healthy and an " +
      "operator has been alerted. Resets are paused until it's back. " +
      (result.maintenance_reason ? `(${result.maintenance_reason})` : "");
    if (btn) btn.disabled = true;
  } else {
    banner.hidden = true;
    if (btn) btn.disabled = false;
  }
}

async function loadStatus() {
  const { result } = await api("POST", "/api/action/lab.status");
  renderVMs(result.vms);
  applyMaintenance(result);
  return result.vms;
}

async function doReset() {
  const btn = $("#resetBtn");
  if (!confirm("Reset the lab? Every enclave VM rolls back to the golden snapshot — any changes you made are wiped, and your lab-desktop tab (if open) will disconnect and need reopening.")) return;
  btn.disabled = true;
  $("#refreshBtn").disabled = true;
  // Reset blocks for ~2-3 min (rollback + health-check); show a live heartbeat so
  // the screen never looks hung. Cleared in finally on success or failure.
  const t0 = Date.now();
  const hb = setInterval(() => {
    log(`  …still working — ${Math.round((Date.now() - t0) / 1000)}s elapsed (rolling back + health-checking each device)`, "dim");
  }, 15000);
  try {
    log("reset requested — rolling back to golden and verifying the lab…");
    log("this takes about 2–3 minutes; the page updates automatically when it's done…", "dim");
    // The backend now blocks until every VM is rolled back AND the lab is verified
    // healthy, so this response means the lab is genuinely ready (or it 503s).
    const { result } = await api("POST", "/api/action/lab.reset");
    for (const r of result.reset) {
      if (r.skipped) log(`  ${r.name}: skipped (${r.skipped})`, "err");
      else log(`  ${r.name}: rolled back ${r.rollback}`, (r.rollback === "ok" || r.rollback === "slow") ? "dim" : "err");
    }
    // Backend now blocks until verified; a 200 always means health === "ok".
    log("lab reset complete and verified healthy — ready to drive again.", "ok");
  } catch (e) {
    if (e.status === 409) log("a reset is already in progress — please wait.", "err");
    else if (e.status === 503) log("reset failed health-check — the lab was taken offline and an operator alerted.", "err");
    else log(`reset failed: ${e.message}`, "err");
  } finally {
    clearInterval(hb);
    $("#refreshBtn").disabled = false;
    // Re-sync status (re-enables Reset only if not in maintenance / surfaces the
    // banner on a 503). Never let a status blip leave the button stuck disabled.
    try {
      await loadStatus();
    } catch (_) {
      btn.disabled = false;
      log("couldn't refresh lab status — click Refresh to retry.", "err");
    }
  }
}

$("#resetBtn").addEventListener("click", doReset);
$("#refreshBtn").addEventListener("click", async () => {
  try { await loadStatus(); log("state refreshed.", "dim"); }
  catch (e) { log(`could not load state: ${e.message}`, "err"); }
});

// --- API playground ---------------------------------------------------------
function opRow(op) {
  const row = document.createElement("div");
  row.className = "op";
  const inputs = (op.params || []).map((p) =>
    `<input class="op-param" data-name="${p.name}" placeholder="${p.label}${p.example ? " · e.g. " + p.example : ""}" />`
  ).join("");
  row.innerHTML = `
    <div class="op-info">
      <div class="op-label">${op.label}${op.mutating ? ' <span class="pill write">write</span>' : ""}</div>
      <div class="op-sum">${op.summary}</div>
    </div>
    <div class="op-run">${inputs}<button class="btn small run" type="button">Run</button></div>`;
  row.querySelector(".run").addEventListener("click", () => runOp(op, row));
  return row;
}

function renderCatalog(ops) {
  const wrap = $("#catalog");
  wrap.innerHTML = "";
  if (!ops.length) { wrap.innerHTML = `<div class="loading">No operations available.</div>`; return; }
  for (const op of ops) wrap.appendChild(opRow(op));
}

async function runOp(op, row) {
  const btn = row.querySelector(".run");
  const out = $("#apiResult");
  const params = {};
  let missing = false;
  row.querySelectorAll(".op-param").forEach((inp) => {
    params[inp.dataset.name] = inp.value.trim();
    if (!inp.value.trim()) missing = true;
  });
  if ((op.params || []).length && missing) { log(`${op.label}: fill in the field first.`, "err"); return; }
  btn.disabled = true;
  out.hidden = false;
  out.textContent = `running ${op.id}…`;
  log(`API ▸ ${op.label}`);
  try {
    const data = await api("POST", `/api/action/${op.id}`, (op.params || []).length ? params : {});
    out.textContent = JSON.stringify(data.result, null, 2);
    log(`API ◂ ${op.label} — ok`, "ok");
    if (op.mutating) loadStatus().catch(() => {});
  } catch (e) {
    out.textContent = `Error: ${e.message}`;
    log(`API ◂ ${op.label} — ${e.message}`, "err");
  } finally {
    btn.disabled = false;
  }
}

async function loadCatalog() {
  try { renderCatalog(await api("GET", "/api/catalog")); }
  catch (e) { $("#catalog").innerHTML = `<div class="loading">Couldn't load the API operations — the lab may be waking up. Try Refresh in a moment.</div>`; }
}

// --- booking handoff: a ?session=<token> link from a reserved slot ------------
async function checkBookingSession() {
  const url = new URL(location.href);
  const token = url.searchParams.get("session");
  if (!token) return;
  const banner = $("#sessionBanner");
  banner.hidden = false;
  banner.className = "session-banner";
  banner.textContent = "checking your booking…";
  try {
    // Claim binds the token to the signed-in identity server-side; the browser
    // only ever gets an httponly sid cookie back, never the token again.
    const s = await api("POST", "/api/session/claim", { token });
    const until = fmtTime(s.expires_at);
    banner.className = "session-banner ok";
    banner.textContent = `🎟  Reserved lab session claimed — your booked time runs until ${until}.`;
    log(`booked session active until ${until}`, "ok");
  } catch (e) {
    banner.className = "session-banner bad";
    banner.textContent = (e.status === 403)
      ? "This booking link belongs to a different signed-in account, or has expired — sign in with the email you booked with, or book a fresh slot."
      : "This booking link is invalid or has expired — book again to reserve a fresh slot.";
  }
  // strip the token from the address bar so it isn't re-shared or re-run on refresh
  url.searchParams.delete("session");
  history.replaceState({}, "", url.pathname + url.search);
}

// --- identity + booking-state gate --------------------------------------------
// The portal tells us who the edge verified us as and whether a booked window is
// none / upcoming / active. The UI mirrors what the backend enforces: visitors
// without an active booking get the booking landing, not the lab controls.
let ME = null;
let tickTimer = null;

async function loadMe() {
  try { ME = await api("GET", "/api/me"); }
  catch (_) { ME = null; } // /api/me unavailable -> legacy behavior (show the lab)
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtLeft(secs) {
  secs = Math.max(0, Math.floor(secs));
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : (m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`);
}

function unlocked() {
  // Fail CLOSED: no verified identity -> no lab. The enclave is single-tenant, so
  // the ONLY way in is to be the current occupant (your booked slot is live and
  // you hold the lab). Admins are not exempt — they book like everyone else.
  if (!ME || !ME.email) return false;
  return !!(ME.booking && ME.booking.occupant_is_me);
}

function applyAccess() {
  const b = (ME && ME.booking) || { state: "none" };
  const panels = ["#statusPanel", "#actionsPanel", "#playgroundPanel"];
  if (ME && ME.email) {
    const who = $("#whoami"), out = $("#signOut");
    who.hidden = false;
    who.textContent = ME.email + (ME.role === "admin" ? " · admin" : "");
    out.hidden = false;
    if (ME.sign_out) out.href = ME.sign_out;
  }
  if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
  const bp = $("#bookingPanel"), text = $("#bookingText"), cta = $("#bookingCTA"),
        cd = $("#bookingCountdown"), nowBtn = $("#bookNowBtn"), banner = $("#sessionBanner");

  if (unlocked()) {
    bp.hidden = true;
    panels.forEach((s) => { $(s).hidden = false; });
    // The occupant sees how long the lab is theirs.
    const until = b.expires_at || b.occupant_until;
    banner.hidden = false;
    banner.className = "session-banner ok";
    const paint = () => {
      const left = (until || 0) - Date.now() / 1000;
      if (left <= 0) { location.reload(); return; }
      banner.textContent = `🎟  Reserved session — the lab is yours until ${fmtTime(until)} (${fmtLeft(left)} left).`;
    };
    paint();
    tickTimer = setInterval(paint, 1000);
    return true;
  }

  panels.forEach((s) => { $(s).hidden = true; });
  bp.hidden = false;
  banner.hidden = true;

  if (b.state === "upcoming") {
    $("#bookingTitle").textContent = "Your session is booked";
    text.textContent = "The lab is reserved for one visitor at a time. This page unlocks automatically the moment your slot begins — leave it open, or come back at your time.";
    cta.hidden = true;
    cd.hidden = false;
    const paint = () => {
      const left = b.starts_at - Date.now() / 1000;
      if (left <= 0) { location.reload(); return; }
      cd.textContent = `Starts ${fmtTime(b.starts_at)} — in ${fmtLeft(left)}`;
    };
    paint();
    tickTimer = setInterval(paint, 1000);
  } else if (b.occupied && !b.occupant_is_me) {
    // Someone else holds the single-tenant lab — even admins wait their turn.
    $("#bookingTitle").textContent = "The lab is in use";
    text.textContent = "Another visitor has the lab right now — it's one session at a time. Reserve a later slot below, or check back when it frees.";
    cta.hidden = false;
    nowBtn.hidden = true;           // can't start now while it's occupied
    cd.hidden = false;
    $("#bookIdentity").textContent = (ME && ME.email) || "";
    const paint = () => {
      const left = (b.occupant_until || 0) - Date.now() / 1000;
      if (left <= 0) { location.reload(); return; }
      cd.textContent = `In use for about ${fmtLeft(left)} more`;
    };
    paint();
    tickTimer = setInterval(paint, 1000);
    wireBooking();
  } else {
    $("#bookingTitle").textContent = "Reserve your session";
    text.textContent = "The whole lab is yours for a private window — one visitor at a time, reset to a clean baseline at the start. Booking is free; this page unlocks at your slot.";
    cta.hidden = false;
    nowBtn.hidden = false;
    cd.hidden = true;
    $("#bookIdentity").textContent = (ME && ME.email) || "";
    wireBooking();
  }
  return false;
}

let bookingWired = false;
function wireBooking() {
  if (bookingWired) return;
  bookingWired = true;
  $("#bookNowBtn").addEventListener("click", () => doBook(null));
  $("#bookLaterBtn").addEventListener("click", () => {
    const v = $("#bookWhen").value;
    if (!v) { showBookMsg("Pick a date and time first.", "bad"); return; }
    doBook(new Date(v).toISOString());
  });
}

function showBookMsg(text, cls) {
  const el = $("#bookMsg");
  el.hidden = false;
  el.className = "bookmsg" + (cls ? " " + cls : "");
  el.textContent = text;
}

async function doBook(startIso) {
  const btns = [$("#bookNowBtn"), $("#bookLaterBtn")];
  btns.forEach((b) => (b.disabled = true));
  showBookMsg(startIso ? "Reserving your slot…" : "Starting your session…", "");
  try {
    const res = await api("POST", "/api/book", startIso ? { start: startIso } : {});
    const when = res.start ? fmtTime(new Date(res.start).getTime() / 1000) : "your slot";
    showBookMsg(`✓ Reserved for ${when}. Unlocking…`, "ok");
    log(`lab reserved for ${when}`, "ok");
    // The Cal.com webhook mints the session a moment later; poll /api/me until it
    // shows, then re-render (active → unlocked, future → countdown).
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      await loadMe();
      if (ME && ME.booking && ME.booking.state !== "none") break;
    }
    if (applyAccess()) { await loadStatus().catch(() => {}); loadCatalog(); }
  } catch (e) {
    btns.forEach((b) => (b.disabled = false));
    if (e.status === 409) showBookMsg("That time was just taken — pick another.", "bad");
    else if (e.status === 401) showBookMsg("Please sign in again to book.", "bad");
    else showBookMsg("Couldn't book right now — try again in a moment.", "bad");
  }
}

(async () => {
  await checkBookingSession();
  await loadMe();
  if (!applyAccess()) return; // locked: the booking landing is showing
  try { await loadStatus(); }
  catch (e) { $("#vms").innerHTML = `<div class="loading">The lab is waking up — give it a moment, then click Refresh.</div>`; }
  loadCatalog();
})();
