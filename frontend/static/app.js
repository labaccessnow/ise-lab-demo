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

(async () => {
  try { await loadStatus(); }
  catch (e) { $("#vms").innerHTML = `<div class="loading">Lab backend unreachable: ${e.message}</div>`; }
})();
