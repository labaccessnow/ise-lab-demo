# Terraform — multi-vendor platform provisioning

The **VM-lifecycle layer** of the ise-lab IaC stack. It declaratively defines the
Proxmox VMs for the multi-vendor enclave (Cisco / Palo Alto / Aruba / Arista),
replacing the ad-hoc `qm create` commands those VMs were first built with.

```
Terraform (this layer)   →  create VMs from EVE qcow2 images: e1000 NICs, disks, serial, RAM
        ↓
Ansible (../ansible)     →  in-guest config (ISE / WLC / DC; appliance day-1 where scriptable)
        ↓
Python backend (../backend) →  runtime control plane: golden-snapshot one-click reset, lab-state
```

Provider: [`bpg/proxmox`](https://registry.terraform.io/providers/bpg/proxmox). Auth is an
API token scoped to the `iselab` pool — the same blast-radius boundary the backend enforces.

## Platforms

| VM  | Name      | Vendor / role                | Status   |
|-----|-----------|------------------------------|----------|
| 142 | nad-sw    | Cat9000v-UADP wired NAD (8×dot1x) | ok   |
| 145 | fmcv      | Firepower Management Center 7.7 | pending |
| 146 | ftdv      | Firepower Threat Defense 7.7 | pending  |
| 147 | paloalto  | Palo Alto VM-Series 11.2     | ok       |
| 148 | clearpass | Aruba ClearPass CLABV 6.12   | pending  |
| 150 | c8000v    | Catalyst 8000v 17.16         | pending  |
| 151 | veos      | Arista vEOS 4.33             | ok       |
| 152 | arubacx   | Aruba CX 10.14               | ok       |

`ok` = configured + golden-snapshotted (in the reset baseline). `pending` = build unfinished.

## Lessons baked in (see comments in `locals.tf`)

- **e1000, not virtio**, for appliance mgmt/data NICs — on virtio the link never comes
  up (hit on the Cat9000v, FMC, and PA).
- **Palo Alto**: e1000 *and* PAN-OS `set deviceconfig system type static` — setting the
  mgmt IP alone leaves the interface in `dhcp-client`.
- **FMC**: never hard-stop it (unclean shutdown → multi-hour DB check); 32 GB RAM;
  ~30-min first-boot DB-init.
- **ClearPass CLABV**: needs a 2nd ~400 GB disk at SCSI 0:1 (shared `virtio-scsi-pci`,
  boot scsi1 first) as the primary boot image.

## Usage

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in real PVE endpoint + token
terraform init
terraform plan
```

### Adopting the VMs that already exist (don't recreate them!)

The `ok` platforms are already running with `golden` snapshots — **import** them so
Terraform manages them in place instead of destroying/recreating:

```bash
terraform import 'proxmox_virtual_environment_vm.platform["paloalto"]' <node>/147
# repeat for nad-sw/142, veos/151, arubacx/152
```

Pin each NIC's `mac` in `locals.tf` to the running value before importing so the plan
shows no diff (appliance configs and golden snapshots are MAC-sensitive).

### Fresh build

For a clean enclave (no existing VMs), `terraform apply` creates every platform,
streaming each EVE image in via `import_from`. The appliance **first-boot wizards**
(PA / FMC / ClearPass) still need scripted console driving afterwards — Terraform
builds the VM shell and imports the disk; it can't click through a EULA.

> **Note:** `import_from` reads the qcow2 by absolute path on the node, so the provider's
> `ssh` block must be able to reach it (agent or key for `pve_ssh_user`).
