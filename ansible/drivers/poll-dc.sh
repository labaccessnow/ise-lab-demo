#!/usr/bin/env bash
# Polls VM126 (Windows DC) via the QEMU guest agent until demo.lab is promoted.
PVE=root@${PVE_HOST}
agent_seen=0
for i in $(seq 1 55); do
  if ssh -o BatchMode=yes -o ConnectTimeout=8 "$PVE" "qm agent 126 ping" >/dev/null 2>&1; then
    if [ "$agent_seen" = 0 ]; then echo "[$(date +%T)] iter $i: guest agent ONLINE (Windows installed, qemu-ga up)"; agent_seen=1; fi
    OUT=$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PVE" 'qm guest exec 126 --timeout 10 -- cmd.exe /c "type C:\\dc-ready.txt"' 2>/dev/null)
    if echo "$OUT" | grep -q "DC READY"; then
      echo "[$(date +%T)] iter $i: ===== DC READY ====="
      echo "$OUT" | grep -o 'DC READY.*'
      # confirm AD + DNS services
      ssh -o BatchMode=yes "$PVE" 'qm guest exec 126 --timeout 15 -- powershell -NoProfile -Command "(Get-Service NTDS,DNS,W32Time | Select-Object Name,Status | Format-Table -HideTableHeaders | Out-String).Trim(); try { (Get-ADDomain).DNSRoot } catch {}"' 2>/dev/null | grep -oE '"out-data":.*' | head -1
      exit 0
    fi
    echo "[$(date +%T)] iter $i: agent up, forest promotion still running"
  else
    echo "[$(date +%T)] iter $i: install in progress (guest agent not up yet)"
  fi
  sleep 60
done
echo "[$(date +%T)] TIMEOUT (~55 min) — check noVNC console of VM126"
exit 1
