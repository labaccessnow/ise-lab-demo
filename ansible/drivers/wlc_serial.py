#!/usr/bin/env python3
"""Drive the Catalyst 9800-CL (VM 130) day-0 over `qm terminal` on the PVE host.

⚑ REALITY (2026-06-16, hit live): the 9800-CL console is **VGA, not serial0** — so
this serial driver does NOT work for day-0. Drive it instead with kbd.py (sendkey) +
shot.sh (screendump), like the Win DC. Also: mgmt IP goes on **interface Vlan1** (SVI),
NOT GigabitEthernet1 (Gi1 is an L2 switchport). And `aaa new-model` needs
`aaa authentication enable default enable` in the same change or `enable` locks out.
Kept for reference; see memory proj-ise-demo-lab for the actual procedure.


Goal of day-0: get the box to a state cisco.ios can reach — mgmt IP on Gi1,
default route, local admin + enable secret, and SSH. Wireless-mgmt interface +
country + RADIUS are done afterward by `ansible/ise-demo/wlc_configure.yml`
(cisco.ios) — keeping this driver to the minimum that unblocks SSH.

  ./wlc_serial.py watch          # tail the console
  ./wlc_serial.py drive          # answer the initial dialog 'no' + push day-0 config

Mirrors ise_serial.py: SSH to the PVE host, pexpect the serial socket, creds
from SOPS (key `cisco_wlc`).  STATUS: scaffold — validate at first provision.
"""
import os, sys, json, subprocess, pexpect

PVE   = "root@${PVE_HOST}"
VMID  = 130
MGMT  = "0.0.0.0"
MASK  = "255.255.255.0"
GW    = "0.0.0.0"
DOMAIN = "demo.lab"
MGMT_IF = "GigabitEthernet1"        # single vNIC = the wireless-mgmt/mgmt interface on 9800-CL

def creds():
    out = subprocess.check_output(
        [os.path.expanduser("~/.local/bin/sops"), "-d",
         os.path.expanduser("~/proxmox-automation/secrets/secrets.sops.json")])
    w = json.loads(out)["cisco_wlc"]
    return w["admin_user"], w["admin_password"], w.get("enable_secret", w["admin_password"])

def spawn(timeout=120):
    cmd = f"ssh -tt -o BatchMode=yes -o ConnectTimeout=8 {PVE} qm terminal {VMID} --iface serial0"
    return pexpect.spawn(cmd, timeout=timeout, encoding="utf-8", codec_errors="ignore")

def watch():
    p = spawn();
    try:
        while True:
            try: sys.stdout.write(p.read_nonblocking(4096, 2))
            except pexpect.TIMEOUT: pass
            except pexpect.EOF: break
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass

def drive():
    user, pw, en = creds()
    p = spawn(timeout=300)
    p.sendline("")
    # IOS-XE fresh boot: decline the initial config dialog + any autoinstall.
    i = p.expect([r"initial configuration dialog\? \[yes/no\]:",
                  r"[Ww]ould you like to terminate autoinstall\? \[yes\]:",
                  r"Press RETURN to get started", r">", r"#", pexpect.TIMEOUT], timeout=300)
    if i == 0:
        p.sendline("no")
        p.expect([r"terminate autoinstall\? \[yes\]:", r"Press RETURN", r">", pexpect.TIMEOUT], timeout=60)
        p.sendline("")
    elif i == 1:
        p.sendline("yes")
    p.sendline("")
    p.expect([r">", r"#", pexpect.TIMEOUT], timeout=60)
    p.sendline("enable"); p.expect([r"#", pexpect.TIMEOUT], timeout=20)
    for line in [
        "configure terminal",
        "hostname wlc-demo",
        f"enable secret {en}",
        f"username {user} privilege 15 secret {pw}",
        f"interface {MGMT_IF}",
        f" ip address {MGMT} {MASK}",
        " no shutdown",
        "exit",
        f"ip route 0.0.0.0 0.0.0.0 {GW}",
        f"ip domain name {DOMAIN}",
        "crypto key generate rsa modulus 2048",
        "ip ssh version 2",
        "line vty 0 15",
        " login local",
        " transport input ssh",
        "exit",
        "end",
        "write memory",
    ]:
        p.sendline(line)
        p.expect([r"#", r"\]:", r"\? \[yes/no\]:", pexpect.TIMEOUT], timeout=30)
    print(f"\n[wlc_serial] day-0 pushed: SSH up on {MGMT}. Now run wlc_configure.yml.")

if __name__ == "__main__":
    {"watch": watch, "drive": drive}.get(sys.argv[1] if len(sys.argv) > 1 else "watch", watch)()
