# ise-lab-demo

A standalone, self-service **multi-vendor security demo lab**. Demo visitors drive — entirely from a gated
website, with no other access to the lab — both:

- **Infrastructure automation**: rebuild / fast-reset Cisco ISE, a Windows DC, a Cisco WLC, and a Palo Alto firewall.
- **API automation**: most of ISE **OpenAPI + ERS**, WLC **RESTCONF**, and **PAN-OS** REST/XML — including
  cross-device **certificate renewal**.

It is **demo-only**: tearing the lab down and rebuilding it *is* the demo. The default visitor action is a
**golden-snapshot reset (~1–2 min)**, not a from-scratch build (ISE first-boot is 45–65 min).

> Separate project from the home-lab `proxmox-automation` — its own repo, secrets, and VMs. The existing
> `demo.lab` enclave is the seed; this repo productionizes it into a self-service platform.

## Architecture (three tiers, hard privilege separation)

```
Internet → Oracle/BunkerWeb edge (LE+WAF, Authelia/visitor-gate)
        → PORTAL FRONTEND (DMZ; no secrets; visitor|admin)
        → BACKEND/RUNNER  (trusted; holds Proxmox token + SOPS key + SSH; allowlisted action catalog)
        → ENCLAVE (VLAN 1800 + sub-VLANs; isolated; snapshots) — ISE · DC(+CA) · WLC · PA · NAD · endpoint · AP
```

A fully compromised visitor session still cannot run an arbitrary command or read a secret: visitors reach only
the frontend, which can only request a fixed allowlist from the backend, which alone holds privilege.

## Layout

```
ansible/    the engine — provision/reset VMs + device config (lifted + extended)
  roles/    proxmox_vm · cisco_ise · (palo_alto, nac_endpoint — to add)
  drivers/  headless console drivers (shot.sh, kbd.py, ise_serial.py, wlc_serial.py, answer/)
backend/    FastAPI + ansible-runner + the allowlisted catalog engine + guardrails
frontend/   the visitor portal (buttons + live logs)
catalog/    generated API operation catalog (ISE/WLC/PA), tagged read/write + visitor/admin
infra/      portal + runner VM provisioning, edge config
secrets/    project SOPS store (encrypted; own age key)
docs/       MkDocs
```

## Status

**Phase 0–1 (foundations + engine lift) — in progress.** See the full phased plan and live status in the
project memory `proj-ise-lab-demo`. The existing `demo.lab` enclave is untouched while this is built.
