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
function setCookie(name, value, maxAge) {
  document.cookie = `${name}=${value}; path=/; max-age=${maxAge}; samesite=lax`;
}

async function checkBookingSession() {
  const url = new URL(location.href);
  const token = url.searchParams.get("session");
  if (!token) return;
  const banner = $("#sessionBanner");
  banner.hidden = false;
  banner.className = "session-banner";
  banner.textContent = "checking your booking…";
  try {
    const s = await api("GET", `/api/session/${encodeURIComponent(token)}`);
    if (!s || !s.valid) throw new Error("invalid");
    setCookie("sid", token, 86400);
    const until = new Date(s.expires_at * 1000)
      .toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    banner.className = "session-banner ok";
    banner.textContent = `🎟  Reserved lab session active — your booked time runs until ${until}.`;
    log(`booked session active until ${until}`, "ok");
  } catch (_) {
    banner.className = "session-banner bad";
    banner.textContent = "This booking link is invalid or has expired — book again to reserve a fresh slot.";
  }
  // strip the token from the address bar so it isn't re-shared or re-run on refresh
  url.searchParams.delete("session");
  history.replaceState({}, "", url.pathname + url.search);
}

(async () => {
  await checkBookingSession();
  try { await loadStatus(); }
  catch (e) { $("#vms").innerHTML = `<div class="loading">The lab is waking up — give it a moment, then click Refresh.</div>`; }
  loadCatalog();
})();
