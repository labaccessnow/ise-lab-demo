"""Allowlisted action registry.

The portal can invoke ONLY the actions defined here. Each carries a required role
and whether it mutates. No free-form input reaches Proxmox/ansible — handlers take
a validated params dict and act only on the enclave allowlist (enforced in proxmox.py).
The broad ISE/WLC/PA API catalog (Phase 5b) plugs in as more entries here.
"""
import os
import time
from dataclasses import dataclass
from typing import Callable

from . import alerts, catalog, health
from .config import (ACTION_TIMEOUT_S, ENCLAVE_VMS, GOLDEN_SNAPSHOT,
                     HEALTH_RETRIES, HEALTH_RETRY_WAIT_S, MAINTENANCE_FLAG,
                     RESET_ORDER)


def maintenance_on() -> bool:
    return os.path.exists(MAINTENANCE_FLAG)


def _set_maintenance(reason: str) -> bool:
    """Persist the offline flag. Returns False if the write itself failed — the
    caller still alerts + raises, so a disk/permission error can't silently drop
    the safety signal."""
    try:
        with open(MAINTENANCE_FLAG, "w") as f:
            f.write(reason)
        return True
    except OSError as e:
        print(f"[reset] FAILED to persist maintenance flag: {type(e).__name__}")
        return False


def _clear_maintenance(px, params):
    try:
        os.remove(MAINTENANCE_FLAG)
        existed = True
    except FileNotFoundError:
        existed = False
    return {"maintenance": "cleared", "was_set": existed}


class LabUnavailable(Exception):
    """The lab is offline (a reset failed health-check / maintenance flag set).
    Surfaced to the visitor as 503, not a 500 stack trace."""


@dataclass(frozen=True)
class Action:
    role: str            # "visitor" | "admin"
    mutating: bool
    summary: str
    fn: Callable         # (px, params) -> dict


def _status(px, params):
    vms = []
    for vmid in RESET_ORDER:
        st = px.vm_status(vmid)
        snaps = [s["name"] for s in px.list_snapshots(vmid) if s.get("name") != "current"]
        vms.append({
            "vmid": vmid, "name": ENCLAVE_VMS[vmid],
            "status": st.get("status"), "golden": GOLDEN_SNAPSHOT in snaps,
        })
    out = {"vms": vms, "maintenance": maintenance_on()}
    # No exists()-then-read TOCTOU: a concurrent clear (this runs without the
    # single-flight lock) could remove the file between the two calls.
    try:
        with open(MAINTENANCE_FLAG) as f:
            out["maintenance_reason"] = f.read()
    except FileNotFoundError:
        pass
    return out


def _wait_task(px, upid, timeout=180):
    """Wait for a Proxmox task. Returns (done, ok): done=False means it was still
    running at the deadline (NOT a definitive failure — a slow vmstate restore can
    overrun); ok is the exitstatus when it did stop."""
    deadline = time.time() + max(1, timeout)
    while time.time() < deadline:
        st = px.task_status(upid)
        if st.get("status") == "stopped":
            return True, st.get("exitstatus") == "OK"
        time.sleep(2)
    return False, False


def _take_offline(reason: str):
    persisted = _set_maintenance(reason)
    note = "" if persisted else "\n:warning: maintenance flag could NOT be persisted — recheck the runner."
    alerts.notify(f":rotating_light: ISE-lab reset FAILED — lab taken OFFLINE.\n{reason}{note}\n"
                  f"Clear with the admin `lab.clear_maintenance` action after fixing.")
    raise LabUnavailable(reason + " — lab taken offline.")


def _reset(px, params):
    """Roll every enclave VM back to golden, WAIT for completion, then verify the
    lab actually came up healthy. Bounded by ACTION_TIMEOUT_S so the client always
    gets a deterministic answer inside the portal proxy window. On persistent
    failure: take the lab offline + alert, so a visitor never lands on a half-broken
    lab."""
    if maintenance_on():
        raise LabUnavailable("Lab is in maintenance (a prior reset failed). An admin must clear it.")

    deadline = time.time() + ACTION_TIMEOUT_S

    done = []
    rollback_failed = []
    for vmid in RESET_ORDER:
        snaps = [s["name"] for s in px.list_snapshots(vmid)]
        if GOLDEN_SNAPSHOT not in snaps:
            done.append({"vmid": vmid, "skipped": "no golden snapshot"})
            continue
        upid = px.rollback(vmid, GOLDEN_SNAPSHOT)
        budget = int(deadline - time.time())
        stopped, ok = _wait_task(px, upid, timeout=min(180, max(5, budget)))
        # Only a STOPPED-with-bad-exitstatus is a definitive rollback failure; a
        # still-running task at the budget is left for the health check to judge.
        outcome = "ok" if (stopped and ok) else ("FAILED" if stopped else "slow")
        done.append({"vmid": vmid, "name": ENCLAVE_VMS.get(vmid), "rollback": outcome})
        if outcome == "FAILED":
            rollback_failed.append(ENCLAVE_VMS.get(vmid, vmid))
        if time.time() >= deadline:
            _take_offline(f"reset exceeded {ACTION_TIMEOUT_S}s budget during rollbacks")

    # Verify-after: poll device health until healthy, budget hit, or retries spent.
    # Health is authoritative — a 'slow' rollback that nonetheless came up healthy
    # is fine; only a definitive rollback FAILED forces the offline path.
    result = {"ok": False, "checks": [], "unhealthy": []}
    for attempt in range(1, HEALTH_RETRIES + 1):
        try:
            result = health.check_lab()
        except Exception as e:  # any failure counts as unhealthy-this-attempt
            result = {"ok": False, "checks": [],
                      "unhealthy": [{"name": f"verify-error:{type(e).__name__}"}]}
        if result["ok"] and not rollback_failed:
            # Project to name+ok: never ship real enclave IPs/ports to the visitor.
            safe = [{"name": c["name"], "ok": c["ok"]} for c in result["checks"]]
            return {"reset": done, "health": "ok", "checks": safe, "attempts": attempt}
        if rollback_failed or time.time() >= deadline or attempt == HEALTH_RETRIES:
            break
        time.sleep(HEALTH_RETRY_WAIT_S)

    bad = [c["name"] for c in result["unhealthy"]] + [f"rollback:{n}" for n in rollback_failed]
    _take_offline(f"reset health-check FAILED — unhealthy: {', '.join(bad) or 'unknown'}")


def _snapshot_golden(px, params):
    made = []
    for vmid in RESET_ORDER:
        st = px.vm_status(vmid)
        if st.get("status") != "running":
            made.append({"vmid": vmid, "skipped": f"not running ({st.get('status')})"})
            continue
        upid = px.snapshot(vmid, GOLDEN_SNAPSHOT, "ise-lab-demo golden baseline", vmstate=True)
        made.append({"vmid": vmid, "upid": upid})
    return {"golden": made}


ACTIONS: dict[str, Action] = {
    "lab.status":          Action("visitor", False, "Show lab VM state", _status),
    "lab.reset":           Action("visitor", True,  "Reset the lab to the golden snapshot", _reset),
    "lab.snapshot_golden": Action("admin",   True,  "Re-baseline the golden snapshot", _snapshot_golden),
    "lab.clear_maintenance": Action("admin", True,  "Clear the maintenance/offline flag after a fix", _clear_maintenance),
}

# The API playground catalog plugs in as allowlisted actions (Phase 5b). Each op
# becomes an Action whose handler ignores Proxmox and drives the device API.
for _cid, _cop in catalog.CATALOG.items():
    ACTIONS[_cid] = Action(_cop["role"], _cop["mutating"], _cop["summary"],
                           lambda px, params, _op=_cop: _op["call"](params))
