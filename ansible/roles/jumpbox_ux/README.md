# jumpbox_ux

Turns the enclave **jumpbox** (XFCE + xrdp, streamed pixels-only through
Guacamole) into a guided lab landing for visitors:

- a single **"Start the Lab"** desktop icon (default clutter icons hidden);
- **Firefox auto-opens** a branded start page on login, with one card per device;
- Firefox onboarding / telemetry / first-run nags suppressed system-wide;
- the jumpbox clock re-syncs to the **enclave DC** (not real-world time), so it
  stays consistent with the rest of the golden after a reset.

The visitor never gets network reach or credentials into the enclave — they
drive device GUIs as pixels over RDP. The start page just gives them the map.

## Run

The jumpbox is SSH-reachable (unlike the enclave devices, which are provisioned
via the PVE API). It's already wired into `inventory.yml` (group `jumpbox`) with
`host_vars/jumpbox.yml`. Like every other host_vars file, that's committed with
`0.0.0.0` placeholders — substitute the real enclave addresses at deploy time,
then run:

```bash
ansible-playbook -i inventory.yml jumpbox_ux.yml -l jumpbox
```

## IMPORTANT — persist to the golden after running

The jumpbox golden is a **vmstate** snapshot: visitors reconnect to the frozen
logged-in session, so the role's effects only reach them once they're baked into
the golden. After a successful run, get the desktop into the exact state a
visitor should see (Firefox maximized on the start page, no stray windows), then
re-cut **only** the jumpbox golden:

```bash
# on the runner, from backend/  (scoped `portal` token can delete + snapshot)
python3 - <<'PY'
from app.proxmox import Proxmox, PROXMOX_NODE
px = Proxmox()
px._req("DELETE", f"/nodes/{PROXMOX_NODE}/qemu/134/snapshot/golden")   # 134 = jumpbox VMID
PY
python3 manage_snapshots.py create-golden   # skips VMs that still have a golden
```
