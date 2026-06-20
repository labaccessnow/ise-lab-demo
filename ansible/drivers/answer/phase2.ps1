# Phase 2: runs once after the forest-promotion reboot (RunOnce). Finalizes
# NTP (isolated/local clock), DNS records ISE needs, WinRM, and a ready marker.
Start-Transcript -Path C:\Windows\Temp\phase2.log -Force

# --- NTP: serve time from the local CMOS clock (no internet in this enclave) ---
w32tm /config /manualpeerlist:"127.127.1.0" /syncfromflags:manual /reliable:yes /update | Out-Null
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Config' -Name AnnounceFlags -Value 5 -ErrorAction SilentlyContinue
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpServer' -Name Enabled -Value 1 -ErrorAction SilentlyContinue
Restart-Service w32time -ErrorAction SilentlyContinue

# --- DNS: reverse zone + pre-create ise1 A/PTR so ISE resolves at its setup ---
Add-DnsServerPrimaryZone -NetworkID '0.0.0.0/24' -ReplicationScope 'Forest' -ErrorAction SilentlyContinue
Add-DnsServerResourceRecordA -ZoneName 'demo.lab' -Name 'ise1' -IPv4Address '0.0.0.0' -CreatePtr -ErrorAction SilentlyContinue

# --- WinRM for later remote management over the SVI --------------------------
Enable-PSRemoting -Force -SkipNetworkProfileCheck -ErrorAction SilentlyContinue

# --- ready marker (polled out-of-band via the guest agent) -------------------
"DC READY $(Get-Date -Format o)  forest=demo.lab  ip=0.0.0.0" | Out-File C:\dc-ready.txt -Encoding ascii
Stop-Transcript
