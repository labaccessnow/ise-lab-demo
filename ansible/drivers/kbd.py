#!/usr/bin/env python3
"""Type a string into a Proxmox VM console via QEMU monitor sendkey.
Usage: kbd.py <vmid> <string>   (use \\n in string for Enter)
"""
import sys, subprocess
PVE = "root@${PVE_HOST}"
vmid, s = sys.argv[1], sys.argv[2]
SPEC = {' ':'spc','.':'dot','-':'minus','\\':'backslash','/':'slash',
        ':':'shift-semicolon','_':'shift-minus','=':'equal','\n':'ret',
        '\t':'tab',',':'comma',';':'semicolon','@':'shift-2','+':'shift-equal',
        '(':'shift-9',')':'shift-0','"':'shift-apostrophe',"'":'apostrophe',
        '!':'shift-1','?':'shift-slash','#':'shift-3','%':'shift-5','*':'shift-8'}
lines = []
for ch in s:
    if ch in SPEC: lines.append("sendkey " + SPEC[ch])
    elif ch.isdigit(): lines.append("sendkey " + ch)
    elif ch.isalpha():
        lines.append("sendkey shift-" + ch.lower() if ch.isupper() else "sendkey " + ch)
    else:
        sys.stderr.write("skip unmapped %r\n" % ch); continue
mon = "\n".join(lines) + "\n"
subprocess.run(["ssh","-o","BatchMode=yes",PVE,"qm monitor %s" % vmid],
               input=mon, text=True, capture_output=True)
print("typed %d chars to vm %s" % (len(s), vmid))
