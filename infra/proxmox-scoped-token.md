# Enclave-scoped Proxmox API token (Phase 0 — REVIEW BEFORE RUNNING)

The portal backend (Tier 2) must hold a Proxmox token that can manage **only** the
ISE-lab VMs — not the home lab. Least privilege via a **resource pool** + a dedicated
**privsep token**, instead of reusing the full-access `james@pve!automation`.

> **Not run yet.** These are additive (new pool/role/user/token; adding existing VMs to a
> pool is non-destructive), but they change Proxmox auth — run on `root@${PVE_HOST}` after
> James signs off. Verify priv names against the running PVE version first.

```sh
# 1) Resource pool for every ISE-lab VM (existing + future)
pveum pool add iselab --comment "ISE demo lab (ise-lab-demo)"
for id in 125 126 130; do pvesh set /pool/iselab -vms $id; done   # ise1, dc-demo, wlc-demo

# 2) Role with exactly the perms the backend needs (provision, snapshot/rollback, power)
pveum role add ISELabAutomation -privs \
  "VM.Allocate VM.Clone VM.Audit VM.Config.Disk VM.Config.CDROM VM.Config.CPU \
   VM.Config.Memory VM.Config.Network VM.Config.Options VM.Config.HWType \
   VM.Console VM.Monitor VM.PowerMgmt VM.Snapshot VM.Snapshot.Rollback \
   Datastore.AllocateSpace Datastore.Audit SDN.Audit SDN.Use"

# 3) Dedicated user + privsep token
pveum user add iselab@pve --comment "ISE lab demo portal backend"
pveum user token add iselab@pve portal --privsep 1      # PRINTS the secret ONCE -> SOPS key `proxmox`

# 4) Scope the token: the pool (VMs), the SSD4 store, and SDN — nothing else
pveum acl modify /pool/iselab   -token 'iselab@pve!portal' -role ISELabAutomation
pveum acl modify /storage/SSD4  -token 'iselab@pve!portal' -role ISELabAutomation
pveum acl modify /sdn/zones     -token 'iselab@pve!portal' -role ISELabAutomation

# 5) Verify the scope
pveum user token permissions iselab@pve portal
```

Then store in this repo's SOPS (`secrets/secrets.sops.json`) as:
`proxmox.user = iselab@pve`, `proxmox.token_name = portal`, `proxmox.token_value = <secret>`
— migrated together with `windc_demo` / `cisco_ise` / `cisco_wlc` (see `secrets/README.md`).

**New VMs** (pa-demo, nad-sw, endpoint, scale-out nodes) must be created **into the
`iselab` pool** (`--pool iselab`) so the scoped token can manage them.
