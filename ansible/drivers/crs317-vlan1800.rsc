# ===== CRS317: VLAN 1800 SVI gateway for the ISE demo enclave (demo.lab) =====
# Additive only. vlan1000 / inside-DMZ BGP mesh / 192.168.88.x are untouched.
# Gateway 0.0.0.0 serves ISE (0.0.0.0) + Win DC (0.0.0.0) on VLAN 1800.

# 1) L3 SVI on the bridge for tag 1800 (bridge-vlan already tags CPU + sfp-sfpplus2)
/interface vlan add name=vlan1800 vlan-id=1800 interface=bridge comment="ISE demo enclave L3"

# 2) Put the SVI in the insidedmz VRF (keeps vlan1000; additive)
/ip vrf set insidedmz interfaces=vlan1000,vlan1800

# 3) Gateway address
/ip address add address=0.0.0.0/24 interface=vlan1800 comment="ISE demo gateway"

# 4) Advertise 0.0.0.0/24 into the inside-DMZ fabric (insert before the final reject)
/routing filter rule add chain=insidedmz-out \
  place-before=[find chain="insidedmz-out" rule="reject"] \
  rule="if (dst==0.0.0.0/24) {accept}" comment="ISE demo subnet advertise"

# ---- verify (read-only) ----
# /ip address print where interface=vlan1800
# /routing filter rule print where chain=insidedmz-out
# /routing bgp advertisements print where peer~"insidedmz"   ;# should list 0.0.0.0/24
