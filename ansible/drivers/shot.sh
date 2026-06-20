#!/usr/bin/env bash
# Grab a console screenshot of a Proxmox VM and convert to PNG on the controller.
# Usage: shot.sh <vmid>   -> writes /tmp/scr<vmid>.png
VMID="${1:?usage: shot.sh <vmid>}"
PVE=root@${PVE_HOST}
ssh -o BatchMode=yes "$PVE" "echo 'screendump /tmp/scr${VMID}.ppm' | qm monitor ${VMID} >/dev/null 2>&1; sleep 1"
scp -q "$PVE:/tmp/scr${VMID}.ppm" "/tmp/scr${VMID}.ppm"
python3 - "$VMID" <<'PY'
import sys,zlib,struct
vmid=sys.argv[1]
f=open(f'/tmp/scr{vmid}.ppm','rb')
assert f.readline().strip()==b'P6'
def tok():
    t=b''
    while True:
        c=f.read(1)
        if c.isspace():
            if t: return t
        elif c==b'#': f.readline()
        else: t+=c
w=int(tok()); h=int(tok()); mx=int(tok()); data=f.read(w*h*3)
def chunk(t,d): return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
raw=bytearray()
for y in range(h): raw.append(0); raw+=data[y*w*3:(y+1)*w*3]
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(raw),9))+chunk(b'IEND',b'')
open(f'/tmp/scr{vmid}.png','wb').write(png)
print(f'/tmp/scr{vmid}.png  ({w}x{h})')
PY
