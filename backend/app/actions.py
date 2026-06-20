"""Allowlisted action registry.

The portal can invoke ONLY the actions defined here. Each carries a required role
and whether it mutates. No free-form input reaches Proxmox/ansible — handlers take
a validated params dict and act only on the enclave allowlist (enforced in proxmox.py).
The broad ISE/WLC/PA API catalog (Phase 5b) plugs in as more entries here.
"""
from dataclasses import dataclass
from typing import Callable

from .config import ENCLAVE_VMS, GOLDEN_SNAPSHOT, RESET_ORDER


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
    return {"vms": vms}


def _reset(px, params):
    done = []
    for vmid in RESET_ORDER:
        snaps = [s["name"] for s in px.list_snapshots(vmid)]
        if GOLDEN_SNAPSHOT not in snaps:
            done.append({"vmid": vmid, "skipped": "no golden snapshot"})
            continue
        done.append({"vmid": vmid, "upid": px.rollback(vmid, GOLDEN_SNAPSHOT)})
    return {"reset": done}


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
}
