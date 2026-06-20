# The automation engine

The engine is the part that builds, resets, and configures the lab. It is Ansible-based, lifted from
a hand-built enclave and extended, and it is what the backend runner invokes on a visitor's behalf.

## Ansible layout

```
ansible/
  provision.yml            provision / rebuild the enclave VMs on Proxmox
  playbooks/
    wlc_configure.yml      bring up the 9800 WLC config
    cert_lifecycle.yml     certificate renewal across devices
  roles/
    proxmox_vm             create VMs from templates (full QEMU, no LXC)
    cisco_ise              ISE config via the cisco.ise collection
  host_vars/ group_vars/   per-host + per-group settings
  drivers/                 headless console drivers for first-boot steps
```

All three playbooks pass `ansible-playbook --syntax-check`. The collections in use are
`cisco.ise` and `paloaltonetworks.panos` (with the `ciscoisesdk` and `pan-os-python` SDKs).

!!! warning "cisco.ise has no `all` action group"
    `cisco.ise` 3.2.0 does **not** ship an `all` module-defaults action group, so `module_defaults`
    are wired **per module** rather than once for the whole collection. Wiring it the convenient way
    fails quietly — worth knowing before you copy a `module_defaults: { group/all: ... }` block from
    another collection.

## Headless first-boot

Some steps happen before any API exists — ISE's and the WLC's first boot are console-only. The
`drivers/` directory holds small headless console drivers that drive those serial consoles
(screenshot, keyboard, and per-device answer files) so a from-scratch build can run unattended up to
the point where the management API comes online and Ansible takes over.

## Least-privilege Proxmox access

The runner does **not** use a root Proxmox credential. It authenticates with a **scoped API token**:

- a dedicated pool containing only the enclave VMs,
- a custom role granting just the VM, datastore, SDN, and pool privileges the automation needs,
- a privilege-separated token whose ACLs are limited to that pool, the lab's storage, and the SDN
  zones.

A functional test confirms the token sees **exactly** the enclave VMs and nothing else. The token
secret is generated straight into the project SOPS store and never printed.

## The action catalog (what the backend will run)

The backend exposes an **allowlisted** set of named actions rather than free-form playbook runs.
Early entries:

| Action | Role | Effect |
|--------|------|--------|
| `lab.status` | visitor | read enclave VM + service status |
| `lab.reset` | visitor | roll the enclave back to the golden snapshot |
| `lab.snapshot_golden` | admin | (re)cut the golden snapshot from a healthy state |

Each action is an enum the frontend can name but not modify. The backend enforces a **single-flight
lock** (one destructive operation at a time), a **per-session rate limit**, timeouts, and secret
scrubbing on the streamed output. Read actions are available to everyone; writes that are
snapshot-recoverable are open to visitors; anything touching system, deployment, licensing, or
certificate binding is admin-only.
