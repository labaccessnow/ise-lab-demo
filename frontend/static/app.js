"use strict";

const $ = (s) => document.querySelector(s);
const logEl = $("#log");

const ROLES = {
  "ise1":     "Cisco ISE 3.4 — policy / admin node",
  "dc-demo":  "Windows Server — DNS · NTP · AD · CA",
  "wlc-demo": "Cisco 9800-CL — wireless LAN controller",
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
  if (!r.ok) throw new Error((data && data.detail) || `HTTP ${r.status}`);
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

async function loadStatus() {
  const { result } = await api("POST", "/api/action/lab.status");
  renderVMs(result.vms);
  return result.vms;
}

async function pollUntilReady(timeoutMs = 210000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 4000));
    let vms;
    try { vms = await loadStatus(); } catch (e) { continue; }
    const up = vms.filter((v) => v.status === "running").length;
    log(`… ${up}/${vms.length} VMs running`, "dim");
    if (up === vms.length) return true;
  }
  return false;
}

async function doReset() {
  const btn = $("#resetBtn");
  if (!confirm("Reset the lab? Every enclave VM rolls back to the golden snapshot. Any changes you made will be wiped.")) return;
  btn.disabled = true;
  $("#refreshBtn").disabled = true;
  try {
    log("reset requested — rolling back to golden snapshot…");
    const { result } = await api("POST", "/api/action/lab.reset");
    for (const r of result.reset) {
      if (r.skipped) log(`  VM ${r.vmid}: skipped (${r.skipped})`, "err");
      else log(`  VM ${r.vmid}: rollback started`, "dim");
    }
    log("waiting for the enclave to come back…");
    const ready = await pollUntilReady();
    if (ready) log("lab reset complete — ready to drive again.", "ok");
    else log("still settling — give it another moment, then Refresh.", "err");
  } catch (e) {
    if (String(e.message).includes("409")) log("a reset is already in progress — please wait.", "err");
    else log(`reset failed: ${e.message}`, "err");
  } finally {
    btn.disabled = false;
    $("#refreshBtn").disabled = false;
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
  catch (e) { $("#catalog").innerHTML = `<div class="loading">Could not load operations: ${e.message}</div>`; }
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
  catch (e) { $("#vms").innerHTML = `<div class="loading">Lab backend unreachable: ${e.message}</div>`; }
  loadCatalog();
})();
