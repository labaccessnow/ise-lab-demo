# ise-demo — Ansible template for the `demo.lab` enclave (Windows DC + Cisco ISE + 9800-CL WLC)

One reusable role (`roles/proxmox_vm`) provisions **any** of the three VMs from its
`host_vars/*.yml` `vm_spec`. Same task file, different vars — that's the "use for
all of them" design. Isolated enclave on VLAN 1800 / SSD4; nothing touches dc1/dc2
or production. The DC, ISE, and WLC are **one project on purpose**: one inventory,
one role, shared `group_vars`, and the cross-device wiring (ISE NAD ↔ WLC RADIUS,
both on the DC's DNS) lives together. Background + gotchas: memory `proj-ise-demo-lab`.

📖 **Full step-by-step build (DC → ISE → WLC), with every command + gotcha:
[`docs/BUILD.md`](docs/BUILD.md).**

## Layout
```
group_vars/all.yml          shared enclave net/AD/NTP + SOPS-sourced secrets
host_vars/dc-demo.yml       Win Server 2025 DC  vm_spec  (vmid 126, sata+e1000+seabios)
host_vars/ise1.yml          Cisco ISE 3.4       vm_spec  (vmid 125, scsi+e1000+serial)
host_vars/wlc-demo.yml      Cisco 9800-CL WLC   vm_spec  (vmid 130, ISO install, disk on SSD4, virtio+serial)
roles/proxmox_vm/           creates the VM (community.general.proxmox_kvm)
  tasks/import_image.yml         optional qcow2 boot path (qm importdisk) — used if a vm_spec sets boot_image
  templates/autounattend.xml.j2  Windows unattended install (edition/host/pw param'd)
  templates/setup-dc.ps1.j2      promote forest demo.lab
  templates/phase2.ps1.j2        NTP-authoritative + DNS + firewall + ise1 A/PTR
provision.yml               plays the role across the enclave hosts (serial:1, DC->ISE->WLC)
wlc_configure.yml           cisco.ios CLI: wire the WLC as an ISE RADIUS NAD (post day-0)
requirements.yml            community.general + cisco.ios + ansible.netcommon
```

## Prereqs
- Collections: `community.general`, `ansible.windows` (already installed here).
- `sops` on PATH + the age key (group_vars decrypts `secrets/secrets.sops.json`).
  Adjust the `_sops.proxmox.*` key paths in `group_vars/all.yml` to your schema.
- On SSD4's iso store: the ISE ISO, the Win2025 ISO (names in host_vars), and a
  `virtio-win.iso` (symlink the versioned one) for the guest-agent step.

## Workflow
```bash
cd ansible/ise-demo

# 1) Windows DC first — unattended install + promotes demo.lab + serves DNS/NTP
ansible-playbook -i inventory.yml provision.yml --limit dc-demo
#    wait ~25 min, then verify on the DC console:  nslookup ise1.demo.lab -> 0.0.0.0

# 2) ISE — creates the VM and starts the installer
ansible-playbook -i inventory.yml provision.yml --limit ise1
```
Then finish ISE (not Ansible-automatable — serial wizard):
```bash
# After the ISE OS install reboots, DETACH the ISO or it re-enters the ISOLINUX
# auto-reinstall menu (150s countdown):
ssh root@<pve> 'qm stop 125; qm set 125 --delete ide2 --boot order=scsi0; qm start 125'
# Drive the first-boot setup wizard over serial:
~/ise-demo/ise_serial.py drive
# Post-config (Open API/ERS, certs, AD-join demo.lab): roles/cisco_ise (../roles).
```

### 3) WLC — Catalyst 9800-CL (the ISE NAD)
**Prereq (manual, CCO-gated):** download `C9800-CL-universalk9.17.12.07a.iso` from
software.cisco.com (Catalyst 9800-CL Wireless Controller for Cloud → IOS XE **17.12.7a**,
the current Gold Star → the **`.iso`**; Cisco doesn't post a standalone qcow2 for this
build) and stage it at `/mnt/pve/SSD4/template/iso/` on the PVE host (match `install_iso`
to the exact name). The disk lands on **SSD4** (same tier as ise1/dc-demo; ~281 GB
free). Also create SOPS key `cisco_wlc`
(`admin_user`/`admin_password`/`enable_secret`/`radius_secret`).
```bash
# Create the VM (empty 25 GB disk on SSD4) + boot the ISO installer + start
ansible-playbook -i inventory.yml provision.yml --limit wlc-demo
# After it installs + reboots, detach the ISO (avoids re-install on next boot):
ssh root@<pve> 'qm set 130 --delete ide2 --boot order=scsi0'
# Day-0 over serial (sets mgmt IP 0.0.0.0 + SSH so cisco.ios can connect):
~/ise-demo/wlc_serial.py drive
# Wire it to ISE as a RADIUS NAD (cisco.ios CLI):
ansible-galaxy collection install -r requirements.yml
ansible-playbook -i inventory.yml wlc_configure.yml
# ISE side: add wlc-demo (0.0.0.0) as a Network Device with the SAME radius_secret.
```
Licensing: runs in 90-day eval (full features); unlicensed cap is 50 APs — fine for a
lab NAD. The WLC alone validates the ISE RADIUS path (`test aaa group ISE-GROUP <u> <p>
new-code` → `User rejected` = ISE responding); real 802.1X wireless needs an AP
CAPWAP-joined to the 9800 (later — convert a lab 2802i or use a spare).

**9800-CL day-0 gotchas (hit live 2026-06-16 — see memory `proj-ise-demo-lab`):**
- **Console is VGA, not serial0.** Drive day-0 with `~/ise-demo/kbd.py` (sendkey) +
  `shot.sh` (screendump), like the Win DC — `wlc_serial.py` (serial) does NOT apply.
- **IOS-XE 17.x forces an enable secret at first boot** (min10/upper/lower/digit/no-cisco)
  — that's why `cisco_wlc` creds are generated policy-compliant.
- **Mgmt IP goes on `interface Vlan1` (SVI), not Gi1** — Gi1 is an L2 switchport
  (`ip address` → "Unrecognized command"); it's the VLAN-1 access port carrying the SVI.
- **`aaa new-model` locks out `enable`** unless `aaa authentication enable default enable`
  is set in the same change (now baked into `wlc_configure.yml`).

## Notes
- **NTP fixed here:** `phase2.ps1.j2` configures w32time as an *authoritative local-clock*
  server (`Type=NoSync` + `AnnounceFlags=5` + `NtpServer Enabled=1` + firewall UDP 123 in).
  The original manual build used the invalid `manualpeerlist:127.127.1.0` (Unix ntpd
  syntax) so ISE rejected the DC's time — don't reintroduce that.
- **ISE serial wizard** can't be done by Ansible; `host_vars/ise1.yml: ise_setup` documents
  the answers and `~/ise-demo/ise_serial.py` drives them.
- To add more nodes (e.g. an ISE PSN or a second DC), drop another `host_vars/<name>.yml`
  with a `vm_spec` and add it to `inventory.yml`. No role changes needed.
