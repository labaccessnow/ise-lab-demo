"""Static configuration for the ise-lab-demo backend.

Enclave VMIDs are hard-coded here as a blast-radius backstop: the Proxmox token is
already pool-scoped, and every destructive op is additionally checked against this
set, so the backend can NEVER act on a VM outside the demo enclave.
"""
import os

REPO = os.path.expanduser("~/ise-lab-demo")
SECRETS_SOPS = os.path.join(REPO, "secrets", "secrets.sops.json")
AGE_KEY = os.path.join(REPO, "secrets", "age.key")
SOPS_BIN = os.path.expanduser("~/.local/bin/sops")

# Deployment-specific coordinates come from the environment (see .env.example).
# A gitignored .env at the repo root supplies the real values for local operation;
# the committed defaults are placeholders so nothing site-specific is published.
def _load_dotenv(path):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(os.path.join(REPO, ".env"))

PROXMOX_HOST = os.environ.get("PVE_HOST", "pve.lab.example")
PROXMOX_PORT = int(os.environ.get("PVE_PORT", "8006"))
PROXMOX_NODE = os.environ.get("PVE_NODE", "pve")
POOL = os.environ.get("PVE_POOL", "iselab")

# Cisco 9800-CL WLC RESTCONF endpoint (Phase 5b). Real value in the gitignored .env.
WLC_HOST = os.environ.get("WLC_HOST", "wlc.lab.example")

GOLDEN_SNAPSHOT = "golden"

# The ONLY VMs the portal may touch (blast-radius allowlist). Display names only.
ENCLAVE_VMS = {
    125: "ise1", 126: "dc-demo", 130: "wlc-demo", 134: "jumpbox",
    # Multi-vendor platforms (2026-06-24) — in the reset baseline once golden-snapshotted:
    142: "nad-sw", 147: "paloalto", 151: "veos", 152: "arubacx",
    # Pending golden (add to RESET_ORDER when configured): 145 fmcv, 146 ftdv, 148 clearpass, 150 c8000v
}

# Reset order: DC first (DNS/NTP) so ISE/WLC find their dependencies on rollback;
# then the NADs/firewalls (they depend on ISE for AAA); the jumpbox last, so it
# comes back to a clean desktop after the devices are up.
RESET_ORDER = [126, 125, 130, 142, 147, 151, 152, 134]

# Post-reset health targets — (name, host, port). Real IPs come from the gitignored
# .env (placeholders 0.0.0.0 in the committed .env.example). A reset is only "good"
# when every advertised device answers; otherwise the lab is taken offline + alerted.
HEALTH_TARGETS = [
    ("ise1-https",   os.environ.get("ENCLAVE_ISE_IP",     "0.0.0.0"), 443),   # ISE OpenAPI
    ("ise1-ers",     os.environ.get("ENCLAVE_ISE_IP",     "0.0.0.0"), 9060),  # ISE ERS
    ("dc-demo-dns",  os.environ.get("ENCLAVE_DC_IP",      "0.0.0.0"), 53),    # DC DNS
    ("wlc-demo",     os.environ.get("ENCLAVE_WLC_IP",     "0.0.0.0"), 443),   # WLC mgmt
    ("nad-sw-ssh",   os.environ.get("ENCLAVE_NAD_IP",     "0.0.0.0"), 22),    # Cat9kv NAD
    ("jumpbox-rdp",  os.environ.get("ENCLAVE_JUMPBOX_IP", "0.0.0.0"), 3389),  # Guacamole target
]

# Maintenance flag: when this file exists the lab is OFFLINE (a reset failed its
# health-check). lab.reset is blocked + lab.status reports degraded until an admin
# clears it (lab.clear_maintenance), so a stranger never lands on a half-broken lab.
MAINTENANCE_FLAG = os.path.join(os.path.dirname(__file__), "..", ".maintenance")

# Post-reset verification tuning.
HEALTH_RETRIES = 5          # health-check attempts after rollbacks complete
HEALTH_RETRY_WAIT_S = 10    # seconds between attempts (vmstate restore is fast)

# Guardrails
RATE_LIMIT_WINDOW_S = 60
RATE_LIMIT_MAX = 30         # per real client-IP per window; ONLY mutating actions
                           # (reset/create) count — cheap reads/lab.status are exempt,
                           # so an engaged visitor browsing the playground never hits it.
ACTION_TIMEOUT_S = 240     # hard wall-clock cap on a VISITOR-triggered reset; MUST stay
                           # < the Tier-1 portal proxy read timeout (300s) and the edge
                           # timeout, so a slow reset still returns a deterministic 503.
# The background hand-off reset (reset-on-tenant-change) isn't bound by the proxy
# window, so it gets a generous budget — a full 8-VM golden rollback (vmstate) runs
# well past 240s. Tune if the enclave grows.
RESET_HANDOFF_BUDGET_S = int(os.environ.get("RESET_HANDOFF_BUDGET_S", "600"))
