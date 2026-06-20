# Phase 1: runs at first auto-logon (FirstLogonCommands). Configures NIC, installs
# the QEMU guest agent (for headless verification), then promotes the demo.lab forest.
Start-Transcript -Path C:\Windows\Temp\setup-dc.log -Force

# --- 1. Static IP on the (single) physical NIC -------------------------------
$nic = Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select-Object -First 1
if (-not $nic) { $nic = Get-NetAdapter -Physical | Select-Object -First 1 }
Remove-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetRoute    -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress -InterfaceIndex $nic.ifIndex -IPAddress 0.0.0.0 -PrefixLength 24 -DefaultGateway 0.0.0.0 -ErrorAction SilentlyContinue
Set-DnsClientServerAddress -InterfaceIndex $nic.ifIndex -ServerAddresses 127.0.0.1

# --- 2. QEMU guest agent (from the virtio-win CD) ----------------------------
$msi = $null
foreach ($v in (Get-Volume | Where-Object DriveLetter)) {
  $p = ($v.DriveLetter + ':\guest-agent\qemu-ga-x86_64.msi')
  if (Test-Path $p) { $msi = $p; break }
}
if ($msi) { Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart" -Wait }

# --- 3. Schedule phase 2 to run after the promotion reboot -------------------
Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce' `
  -Name 'DCPhase2' `
  -Value 'powershell -ExecutionPolicy Bypass -NoProfile -File C:\Windows\Temp\phase2.ps1' `
  -ErrorAction SilentlyContinue

# --- 4. AD DS role + promote a brand-new forest demo.lab ---------------------
Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools
Import-Module ADDSDeployment
$dsrm = ConvertTo-SecureString '__DSRM__' -AsPlainText -Force
Install-ADDSForest `
  -DomainName 'demo.lab' `
  -DomainNetbiosName 'DEMO' `
  -SafeModeAdministratorPassword $dsrm `
  -InstallDns:$true `
  -ForestMode 'WinThreshold' `
  -DomainMode 'WinThreshold' `
  -NoRebootOnCompletion:$false `
  -Force:$true
Stop-Transcript
