#!/usr/bin/env python3
"""Phase 2 — golden snapshot management for the ISE-lab enclave.

  python3 manage_snapshots.py status         # run state + existing snapshots
  python3 manage_snapshots.py create-golden  # snapshot ISE/DC/WLC as 'golden' (with RAM state)
  python3 manage_snapshots.py reset          # rollback all enclave VMs to 'golden'

Only the enclave pool VMs are touched (scoped token + allowlist guard). 'golden' is
taken WITH vmstate, so a rollback restores a live, already-healthy lab — no 45-65 min
ISE re-init.
"""
import sys
import time

from app.config import ENCLAVE_VMS, GOLDEN_SNAPSHOT, RESET_ORDER
from app.proxmox import Proxmox, ProxmoxError


def _snap_names(px, vmid):
    return [s["name"] for s in px.list_snapshots(vmid) if s.get("name") != "current"]


def _wait(px, upid, label):
    while True:
        st = px.task_status(upid)
        if st.get("status") == "stopped":
            ok = st.get("exitstatus") == "OK"
            print(f"    {label}: {'OK' if ok else 'FAILED -> ' + str(st.get('exitstatus'))}")
            return ok
        time.sleep(3)


def cmd_status(px):
    for vmid in RESET_ORDER:
        name = ENCLAVE_VMS[vmid]
        st = px.vm_status(vmid)
        snaps = _snap_names(px, vmid)
        golden = "yes" if GOLDEN_SNAPSHOT in snaps else "NO"
        print(f"  {vmid} {name:<10} status={st.get('status'):<8} golden={golden:<4} snaps={snaps}")


def cmd_create_golden(px):
    for vmid in RESET_ORDER:
        name = ENCLAVE_VMS[vmid]
        st = px.vm_status(vmid)
        if st.get("status") != "running":
            print(f"  SKIP {vmid} {name}: not running ({st.get('status')}) — bring it up healthy first")
            continue
        if GOLDEN_SNAPSHOT in _snap_names(px, vmid):
            print(f"  {vmid} {name}: 'golden' already exists — delete it first to re-baseline")
            continue
        print(f"  snapshotting {vmid} {name} as '{GOLDEN_SNAPSHOT}' (with RAM state)...")
        upid = px.snapshot(vmid, GOLDEN_SNAPSHOT, description="ise-lab-demo golden baseline", vmstate=True)
        _wait(px, upid, f"{name} golden")


def cmd_reset(px):
    for vmid in RESET_ORDER:
        name = ENCLAVE_VMS[vmid]
        if GOLDEN_SNAPSHOT not in _snap_names(px, vmid):
            print(f"  SKIP {vmid} {name}: no 'golden' snapshot")
            continue
        print(f"  rolling back {vmid} {name} to '{GOLDEN_SNAPSHOT}'...")
        upid = px.rollback(vmid, GOLDEN_SNAPSHOT)
        _wait(px, upid, f"{name} rollback")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    px = Proxmox()
    fn = {"status": cmd_status, "create-golden": cmd_create_golden, "reset": cmd_reset}.get(cmd)
    if not fn:
        sys.exit(f"unknown command: {cmd} (status|create-golden|reset)")
    try:
        fn(px)
    except ProxmoxError as e:
        sys.exit(f"Proxmox error: {e}")


if __name__ == "__main__":
    main()
