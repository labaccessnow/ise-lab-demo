#!/usr/bin/env python3
"""Watch / drive the ISE VM (125) serial console via `qm terminal` on the PVE host.

Modes:
  watch [seconds]   connect, print serial output for N sec (default 20)
  send  "<text>"    send text + Enter once
  drive [maxsec]    run the ISE setup wizard end-to-end (answers below)
"""
import sys, time, os, json, subprocess
import pexpect

PVE = "root@${PVE_HOST}"
VMID = "125"
LOG = "/tmp/ise-serial.log"
mode = sys.argv[1] if len(sys.argv) > 1 else "watch"
cmd = f"ssh -tt -o BatchMode=yes -o ConnectTimeout=8 {PVE} qm terminal {VMID} --iface serial0"

def connect(timeout):
    return pexpect.spawn(cmd, timeout=timeout, encoding="utf-8", codec_errors="ignore")

def read_idle(p, idle=1.8, cap=20):
    buf, start = "", time.time()
    while time.time() - start < cap:
        try:
            buf += p.read_nonblocking(4096, timeout=idle)
        except pexpect.TIMEOUT:
            if buf.strip():
                break
        except pexpect.EOF:
            break
    return buf

if mode == "watch":
    dur = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    p = connect(dur + 20)   # passive: never send anything in watch mode
    buf, end = "", time.time() + dur
    while time.time() < end:
        try: buf += p.read_nonblocking(8192, timeout=2)
        except pexpect.TIMEOUT: pass
        except pexpect.EOF: break
    print(buf[-6000:] if buf else "(no serial output this window)")
    try: p.sendcontrol("o"); p.close(force=True)
    except Exception: pass

elif mode == "send":
    p = connect(20); time.sleep(1)
    p.send(sys.argv[2] + "\r"); time.sleep(2)
    try: print(p.read_nonblocking(8192, timeout=3)[-3000:])
    except Exception: pass
    try: p.sendcontrol("o"); p.close(force=True)
    except Exception: pass

elif mode == "waitup":
    import re as _re
    maxsec = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
    p = connect(maxsec + 30)
    end = time.time() + maxsec
    while time.time() < end:
        try: p.send("\r")
        except Exception: break
        buf = read_idle(p, idle=1.5, cap=6)
        if buf and _re.search(r"login:|/admin#|/admin>", buf, _re.I):
            print("ISE PROMPT DETECTED:")
            print(buf[-400:])
            try: p.sendcontrol("o"); p.close(force=True)
            except Exception: pass
            sys.exit(0)
        time.sleep(18)
    print("waitup timeout after %ds — still initializing or stuck" % maxsec)

elif mode == "drive":
    maxsec = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    sec = json.loads(subprocess.run(
        [os.path.expanduser("~/.local/bin/sops"), "-d",
         os.path.expanduser("~/proxmox-automation/secrets/secrets.sops.json")],
        capture_output=True, text=True).stdout)
    PW = sec["cisco_ise"]["cli_password"]
    # (all keywords lowercased) -> response ; checked in order, first full match wins
    RULES = [
        (["re-enter", "password"], PW, "pw-confirm"),
        (["confirm", "password"], PW, "pw-confirm"),
        (["enter", "password"], PW, "pw"),
        (["password:"], PW, "pw"),
        (["login:"], "setup", "login"),
        (["ipv6"], "N", "ipv6"),
        (["ip v6"], "N", "ipv6"),
        (["another", "name server"], "N", "more-ns"),
        (["another", "nameserver"], "N", "more-ns"),
        (["add", "nameserver"], "N", "more-ns"),
        (["secondary", "ntp"], "N", "more-ntp"),
        (["another", "ntp"], "N", "more-ntp"),
        (["hostname"], "ise1", "hostname"),
        (["ip address"], "0.0.0.0", "ip"),
        (["netmask"], "255.255.255.0", "netmask"),
        (["network mask"], "255.255.255.0", "netmask"),
        (["default gateway"], "0.0.0.0", "gw"),
        (["gateway"], "0.0.0.0", "gw"),
        (["dns domain"], "demo.lab", "domain"),
        (["domain"], "demo.lab", "domain"),
        (["primary nameserver"], "0.0.0.0", "ns"),
        (["nameserver"], "0.0.0.0", "ns"),
        (["name server"], "0.0.0.0", "ns"),
        (["ntp server"], "0.0.0.0", "ntp"),
        (["timezone"], "UTC", "tz"),
        (["time zone"], "UTC", "tz"),
        (["ssh"], "Y", "ssh"),
        (["username"], "admin", "username"),
        (["continue"], "Y", "continue"),
    ]
    p = connect(maxsec + 30)
    logf = open(LOG, "a")
    initial = sys.argv[3] if len(sys.argv) > 3 else ""
    if initial:                       # resume: answer the prompt already on-screen
        time.sleep(1); p.send(initial + "\r"); time.sleep(0.6)
    else:
        p.send("\r")
    pw_confirmed = False
    drain_until = None
    end = time.time() + maxsec
    while time.time() < end:
        buf = read_idle(p)
        if not buf.strip():
            if drain_until and time.time() > drain_until:
                print(">> post-setup drain complete; exiting driver"); break
            continue
        logf.write(buf); logf.flush()
        tail = buf[-500:].lower()
        if drain_until:
            if time.time() > drain_until:
                print(">> post-setup drain complete; exiting driver"); break
            continue
        # ONLY act on a genuine waiting prompt (ends with :/?/]). Streaming install/
        # boot output (e.g. "Configuring openssh") never ends this way -> never misfires.
        if not tail.rstrip().endswith((":", "?", "]")):
            continue
        matched = False
        for kws, resp, name in RULES:
            if all(k in tail for k in kws):
                shown = "****" if "pw" in name else repr(resp)
                print(f">> {name}: send {shown}")
                p.send(resp + "\r")
                matched = True
                if name == "pw-confirm":
                    pw_confirmed = True
                    drain_until = time.time() + 90  # log the rest, stop driving
                time.sleep(0.6)
                break
        if not matched:
            print("UNKNOWN PROMPT — stopping for manual handling. Tail:\n" + buf[-600:])
            break
    try: p.sendcontrol("o"); p.close(force=True)
    except Exception: pass

elif mode == "appstatus":
    sec = json.loads(subprocess.run(
        [os.path.expanduser("~/.local/bin/sops"), "-d",
         os.path.expanduser("~/proxmox-automation/secrets/secrets.sops.json")],
        capture_output=True, text=True).stdout)
    user = sec["cisco_ise"].get("cli_user", "admin")
    pw = sec["cisco_ise"]["cli_password"]
    p = connect(200)
    p.send("\r")
    i = p.expect([r"login:", r"/admin#", r"/admin>", pexpect.TIMEOUT], timeout=20)
    if i == 0:
        p.sendline(user)
        p.expect([r"[Pp]assword:"], timeout=15)
        p.sendline(pw)
        j = p.expect([r"/admin#", r"/admin>", r"[Ii]ncorrect", pexpect.TIMEOUT], timeout=30)
        if j >= 2:
            print("LOGIN FAILED or not at CLI");
            try: p.close(force=True)
            except Exception: pass
            sys.exit(1)
    p.sendline("terminal length 0")
    p.expect([r"/admin#", pexpect.TIMEOUT], timeout=10)
    for cmd in ["show ntp", "show clock", "show application status ise"]:
        p.sendline(cmd)
        p.expect([r"/admin#", pexpect.TIMEOUT], timeout=90)   # read until the next prompt
        print(f"\n===== {cmd} =====")
        print(p.before.strip())
    try: p.sendline("exit"); p.sendcontrol("o"); p.close(force=True)
    except Exception: pass

elif mode == "appwait":
    import re as _re
    sec = json.loads(subprocess.run(
        [os.path.expanduser("~/.local/bin/sops"), "-d",
         os.path.expanduser("~/proxmox-automation/secrets/secrets.sops.json")],
        capture_output=True, text=True).stdout)
    user = sec["cisco_ise"].get("cli_user", "admin"); pw = sec["cisco_ise"]["cli_password"]
    maxsec = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    p = connect(maxsec + 60); p.send("\r")
    if p.expect([r"login:", r"/admin#", r"/admin>", pexpect.TIMEOUT], timeout=25) == 0:
        p.sendline(user); p.expect([r"[Pp]assword:"], timeout=15); p.sendline(pw)
        if p.expect([r"/admin#", r"/admin>", r"[Ii]ncorrect", pexpect.TIMEOUT], timeout=30) >= 2:
            sys.exit("login failed")
    p.sendline("terminal length 0"); p.expect([r"/admin#", pexpect.TIMEOUT], timeout=10)
    end = time.time() + maxsec
    while time.time() < end:
        p.sendline("show application status ise"); time.sleep(3)
        out = read_idle(p, idle=4.0, cap=45)
        line = next((l.strip() for l in out.splitlines() if l.strip().startswith("Application Server")), "")
        low = line.lower()
        running = ("running" in low) and ("not running" not in low)
        print("Application Server: " + (line.replace("Application Server", "").strip() or "?"), flush=True)
        if running:
            print("===== APPLICATION SERVER RUNNING — ISE admin GUI is up (https://0.0.0.0) =====")
            break
        time.sleep(50)
    else:
        print("appwait timeout — Application Server still not running")
    try: p.sendcontrol("o"); p.close(force=True)
    except Exception: pass
