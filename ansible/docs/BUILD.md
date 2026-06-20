# ISE Demo Enclave — Full Build Process

End-to-end build of the isolated **`demo.lab`** Cisco ISE enclave on Proxmox:
a Windows Server 2025 DC, a Cisco ISE 3.4 node, and a Cisco Catalyst 9800-CL WLC,
all on **VLAN 1800 / `0.0.0.0/24`** — nothing touches production (`dc1`/`dc2`).

> One reusable Ansible role (`roles/proxmox_vm`) provisions every VM from its
> `host_vars/*.yml` `vm_spec`. The DC, ISE, and WLC are **one project on purpose**:
> shared inventory/`group_vars`, plus the cross-device wiring (ISE↔WLC RADIUS,
> all on the DC's DNS) lives together.

---

## 1. Topology

| VM | VMID | Role | IP | Notes |
|----|------|------|----|-------|
| `dc-demo` | 126 | Win Server 2025 DC+DNS+NTP | `0.0.0.0` | new forest `demo.lab` (NetBIOS DEMO); **build 1st** |
| `ise1` | 125 | Cisco ISE 3.4.0.608b | `0.0.0.0` | `ise1.demo.lab`, 4c/16G/300G; **build 2nd** |
| `wlc-demo` | 130 | Catalyst 9800-CL (IOS-XE 17.12.7a) | `0.0.0.0` | ISE NAD/RADIUS client; **build 3rd** |

- **Gateway:** CRS317 SVI `vlan1800` = `0.0.0.0/24` (VRF `insidedmz`), advertised
  into the inside-DMZ BGP fabric (filter permits `0.0.0.0/24`).
- **Proxmox:** node `${PVE_NODE}`, SDN vnet `v1800` on `vmbr10gD` → CRS317, storage `SSD4`.

---

## 2. Prerequisites

- **Proxmox API token** — SOPS `proxmox` (`user` `james@pve`, `token_name` `automation`,
  `token_value`). The enclave `group_vars/all.yml` maps these.
- **SOPS + age key** on PATH (`group_vars` decrypts `secrets/secrets.sops.json`).
  Keys used: `proxmox`, `windc_demo`, `cisco_ise`, `cisco_wlc`.
- **ISOs staged on SSD4** (`/mnt/pve/SSD4/template/iso/`): Win2025, `virtio-win.iso`,
  `ise-3.4.0.608b.SPA.x86_64.iso`, `C9800-CL-universalk9.17.12.07a.iso`
  (the 9800-CL is the **`.iso`**, not a qcow2 — see §6).
- **Ansible** in `.venv-ansible`; collections: `community.general`, `cisco.ios`,
  `ansible.netcommon` (`ansible-galaxy collection install -r requirements.yml`).
- **Local tooling `~/ise-demo/`** (not in git — headless console drivers):
  - `shot.sh <vmid>` — QEMU VGA screendump → PNG (the only window into a GUI/VGA console).
  - `kbd.py <vmid> "<str>"` — QEMU `sendkey` typist (drives VGA consoles; `\n`=Enter).
  - `ise_serial.py {watch,drive,waitup,appstatus}` — pexpect over `qm terminal` (ISE serial).
  - `wlc_serial.py` — reference only; the 9800-CL day-0 is VGA, not serial (see §6).

All three drivers reach the PVE host as `root@${PVE_HOST}` and run `qm`.

---

## 3. Provisioning model

```bash
cd ansible/ise-demo
ansible-galaxy collection install -r requirements.yml
# serial:1 keeps DC→ISE→WLC order
ansible-playbook -i inventory.yml provision.yml --limit dc-demo
ansible-playbook -i inventory.yml provision.yml --limit ise1
ansible-playbook -i inventory.yml provision.yml --limit wlc-demo
```

`roles/proxmox_vm` builds three flavours from `vm_spec`:
- **Windows DC** — empty disk + install ISO + a generated answer ISO (`build_answer_iso`).
- **Cisco ISE** — empty disk + install ISO (serial-driven setup wizard).
- **9800-CL WLC** — empty disk + install ISO (VGA-driven day-0). A `boot_image`
  (qcow2-import) path also exists (`tasks/import_image.yml`) but is unused here.

Per-host `vm_storage` overrides the default storage (SSD4) if a VM should live elsewhere.

---

## 4. Phase 1 — Windows DC (`dc-demo`)

```bash
ansible-playbook -i inventory.yml provision.yml --limit dc-demo
# ~25 min unattended install + promotion, then on the DC console:
#   nslookup ise1.demo.lab  ->  0.0.0.0
```

- `seabios` + **SATA** disk + **e1000** NIC (native drivers, no virtio injected).
- `templates/autounattend.xml.j2` (unattended install) + `setup-dc.ps1.j2`
  (promote forest `demo.lab`) + `phase2.ps1.j2` (DNS + NTP-authoritative + firewall + `ise1` A/PTR).
- Creds: SOPS `windc_demo`.

**Gotchas**
- **No guest agent** (only `qemu-ga`, not the virtio-serial driver) → `qm agent` never
  works. Drive headless via `shot.sh` (screendump) + `kbd.py` (sendkey).
- **NTP:** `phase2.ps1.j2` sets w32time **authoritative local-clock**
  (`Type=NoSync` + `AnnounceFlags=5` + `NtpServer Enabled=1` + firewall UDP 123 in).
  The original manual build used `manualpeerlist:127.127.1.0` (Unix-ntpd syntax,
  **invalid** for w32tm) so ISE rejected the DC's time — do **not** reintroduce it.

---

## 5. Phase 2 — Cisco ISE (`ise1`)

```bash
ansible-playbook -i inventory.yml provision.yml --limit ise1
# After the OS install reboots, DETACH the ISO (avoids the ISOLINUX auto-reinstall trap):
ssh root@<pve> 'qm stop 125; qm set 125 --delete ide2 --boot order=scsi0; qm start 125'
# Drive the first-boot setup wizard over serial:
~/ise-demo/ise_serial.py drive
```

- `seabios` + **virtio-scsi** disk + **e1000** NIC + `serial0 socket`.
- Creds: SOPS `cisco_ise` (`cli_*` = SSH/console admin; `gui_*` = web admin).

**Gotchas**
- **ISOLINUX reinstall trap:** after the OS install ISE reboots and — if the install
  ISO is still attached & first in boot order — lands back in the ISOLINUX menu with a
  **150 s auto-REINSTALL** countdown. Fix: `qm stop`, delete `ide2`, `--boot order=scsi0`, start.
- **Serial install:** at the boot menu pick **[2] Serial Console**, then drive `setup`
  over `qm terminal --iface serial0` (pexpect). Wizard order: hostname/ip/netmask/gw/
  IPv6 Y-N/dnsdomain/nameserver/+more?/ntp/+more?/tz/ssh/user/pw/pw-again, then ping +
  disk-I/O checks (needs ≥50 write / ≥300 read MB/s; SSD4 gives ~600/470).
- **First boot ≈ 45–65 min** (CPU 110–408% the whole time = working, not hung — be patient).
- **NTP:** answer **N** to the wizard NTP-sync prompt if host RTC time is already correct;
  the DC serves NTP once `w32tm /config /syncfromflags:NO /reliable:yes /update` is set.

**Post-install (open items):** enable Open API/ERS (⚠️ **GUI-only toggle**, see §8),
AD-join `demo.lab`, run the `cisco_ise` cert role, wire SolarWinds.

---

## 6. Phase 3 — Catalyst 9800-CL WLC (`wlc-demo`)

The 9800-CL is the **ISE NAD (RADIUS client)** for 802.1X / MAB.

### 6.1 Image (CCO-gated, manual)
Download `C9800-CL-universalk9.17.12.07a.iso` from software.cisco.com
(Catalyst 9800-CL Wireless Controller for Cloud → IOS XE **17.12.7a**, current Gold Star →
the **`.iso`**). Stage at `/mnt/pve/SSD4/template/iso/`.
- **Why ISO not qcow2:** Proxmox won't cleanly boot Cisco's prebuilt qcow2 (it's built for
  a specific KVM hardware profile — firmware/disk-bus/machine-type/console mismatch → boot
  loop). The ISO is a hardware-agnostic installer that lays down an install matched to the
  Proxmox VM. (17.12.7a still supports the Aironet 2802i Wave-2 AP; stay off 17.18+.)
- **Sizing:** "Small" profile = 4 vCPU / 8 GB / 25 GB disk on SSD4; `virtio` NIC on `v1800`;
  `serial0 socket`. Creds: SOPS `cisco_wlc` (`admin`/`enable_secret`/`radius_secret`,
  generated policy-compliant).

### 6.2 Provision + install
```bash
ansible-playbook -i inventory.yml provision.yml --limit wlc-demo   # VM 130, boots the ISO
# the ISO installs IOS-XE onto scsi0 (~5-8 min; watch with: ~/ise-demo/shot.sh 130).
# after it installs + reboots, detach the ISO:
ssh root@<pve> 'qm set 130 --delete ide2 --boot order=scsi0'
```

### 6.3 Day-0 (over the **VGA** console — NOT serial)
The 9800-CL console is **VGA, not serial0** (serial0 stays silent). Drive it with
`kbd.py` (sendkey) + `shot.sh` (screendump), like the Windows DC.

1. **Decline the initial dialog:** `kbd.py 130 "no\n"`.
2. **Forced enable secret:** IOS-XE 17.x **forces** an enable secret at first boot
   (min 10 / upper / lower / digit / no "cisco"). Type the SOPS `enable_secret` + confirm.
   → choose **[0]** "go to the IOS command prompt".
3. **PnP noise:** PnP/ZTP autoinstall spews to the console and interferes with typed input —
   send a newline + let it settle before configuring.
4. **Base config** (note the SVI, see gotcha):
   ```
   configure terminal
    no ip domain lookup
    ip domain name demo.lab
    hostname wlc-demo
    interface Vlan1
     ip address 0.0.0.0 255.255.255.0
     no shutdown
    exit
    ip route 0.0.0.0 0.0.0.0 0.0.0.0
    username admin privilege 15 secret <cisco_wlc.admin_password>
    ip ssh version 2
    line vty 0 15
     login local
     transport input ssh
    exit
    crypto key generate rsa modulus 2048
   end
   write memory
   ```
5. Verify SSH: `ping 0.0.0.0` + `nc -z 0.0.0.0 22` from the controller.

**Day-0 gotchas**
- **Mgmt IP goes on `interface Vlan1` (SVI), NOT GigabitEthernet1.** Gi1 is an **L2
  switchport** on the 9800-CL (`ip address` → `% Unrecognized command`); Gi1 is the
  VLAN-1 access port that carries the Vlan1 SVI, egressing untagged onto `v1800`.
- **Console = VGA**, so `wlc_serial.py` (serial pexpect) does not apply — use `kbd.py`/`shot.sh`.

### 6.4 RADIUS to ISE (`wlc_configure.yml`, cisco.ios)
```bash
ansible-playbook -i inventory.yml wlc_configure.yml
```
Configures: `radius server ISE` (`0.0.0.0`, key = `cisco_wlc.radius_secret`),
`aaa group server radius ISE-GROUP`, dot1x/network/accounting method lists,
`aaa server radius dynamic-author` (CoA), and the AAA auth methods.

- **⚠️ `aaa new-model` LOCKS OUT `enable`** (`% Error in authentication`) unless you set
  `aaa authentication enable default enable` (+ `login default local` + `authorization exec
  default local`) **in the same change**. This is baked into `wlc_configure.yml` task 1.
  (Recovery if locked out: fix it from the still-privileged VGA console.)
- ansible `cisco.ios` falls back to **paramiko** (no `ansible-pylibssh`) and can be flaky;
  the config can also be pushed over a direct paramiko session.

### 6.5 Validate
```
wlc-demo# show aaa servers | include RADIUS|State        -> ISE ... State: current UP
wlc-demo# test aaa group ISE-GROUP probeuser BadPass new-code   -> User rejected
```
`User rejected` = ISE received the Access-Request and replied (RADIUS round-trip +
shared-secret confirmed). ✅ WLC is a working ISE NAD.

---

## 7. Consolidated gotchas (quick reference)

| Area | Gotcha | Fix |
|------|--------|-----|
| Proxmox token | `group_vars` had placeholder paths (`api_token_secret`) | map to real SOPS `proxmox.user`/`token_name`/`token_value` |
| proxmox_kvm | `numa: true` rejected by community.general 12.6.1 (wants dict) | drop the `numa` line |
| Win DC | no virtio-serial → `qm agent` fails | drive via `shot.sh` + `kbd.py` |
| Win DC | `manualpeerlist:127.127.1.0` invalid for w32tm | authoritative local-clock NTP |
| ISE | ISOLINUX 150 s auto-reinstall after OS install | detach `ide2`, `boot order=scsi0` |
| ISE | first boot 45–65 min, high CPU | be patient; not hung |
| ISE | API/ERS + admin pw, **GUI-only**; login is a `_QPH_` base64 XHR + OWASP CSRF | use a browser / the GUI; not curl-scriptable |
| 9800-CL | Proxmox won't boot Cisco's qcow2 | use the **`.iso`** installer |
| 9800-CL | console is VGA, not serial0 | `kbd.py`/`shot.sh` |
| 9800-CL | IOS-XE 17.x forces an enable secret at first boot | policy-compliant creds |
| 9800-CL | mgmt IP rejected on Gi1 (L2 switchport) | put it on `interface Vlan1` (SVI) |
| 9800-CL | `aaa new-model` locks out `enable` | set `aaa authentication enable default enable` same change |

---

## 8. Remaining / TODO

- **ISE: enable ERS + OpenAPI** — Administration → System → Settings → API Settings,
  toggle **ERS (Read/Write)** + **OpenAPI** on. ⚠️ GUI-only: ISE's admin login is a
  dojo XHR carrying base64 creds in a `_QPH_` header behind OWASP CSRFGuard, so it is
  **not** cleanly curl-scriptable — use a real browser (or a headless browser that runs
  the JS). The GUI admin password was reset via `application reset-passwd ise admin`
  (now in SOPS `cisco_ise.gui_password`).
- **ISE: add `wlc-demo` (`0.0.0.0`) as a Network Device** (RADIUS, same `radius_secret`)
  + a Wireless-802.1X policy set — needs ERS/OpenAPI (above) or the GUI.
- **AP:** join a Cisco 2802i to `wlc-demo` for real 802.1X wireless — ME→CAPWAP convert
  (reverse of the ME conversion runbook), cable onto VLAN 1800, discover the WLC
  (DHCP opt 43 / `capwap ap primary-base wlc-demo 0.0.0.0`), then a `wlan`/policy-profile/
  policy-tag bound to the dot1x method lists.

---

## 9. Repo layout

```
group_vars/all.yml          enclave net/AD/NTP + SOPS-sourced secrets
host_vars/dc-demo.yml       Win2025 DC vm_spec  (126, sata+e1000+seabios, answer ISO)
host_vars/ise1.yml          ISE 3.4   vm_spec  (125, scsi+e1000+serial)
host_vars/wlc-demo.yml      9800-CL   vm_spec  (130, ISO install, virtio+serial, SSD4)
inventory.yml               enclave hosts (serial:1 order)
provision.yml               plays proxmox_vm across the enclave
wlc_configure.yml           cisco.ios: WLC -> ISE RADIUS NAD
requirements.yml            community.general + cisco.ios + ansible.netcommon
roles/proxmox_vm/
  tasks/main.yml            create VM from vm_spec (ISO or qcow2-import)
  tasks/import_image.yml    optional qcow2 boot-image import (qm importdisk)
  templates/*.j2            Windows autounattend / DC promote / NTP+DNS
docs/BUILD.md               this document
```

Background, live state, and the running gotcha log also live in memory `proj-ise-demo-lab`.
