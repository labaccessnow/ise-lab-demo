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

GOLDEN_SNAPSHOT = "golden"

# The ONLY VMs the portal may touch (blast-radius allowlist). Display names only.
ENCLAVE_VMS = {125: "ise1", 126: "dc-demo", 130: "wlc-demo", 134: "jumpbox"}

# Reset order: DC first (DNS/NTP) so ISE/WLC find their dependencies on rollback;
# the jumpbox last, so it comes back to a clean desktop after the devices are up.
RESET_ORDER = [126, 125, 130, 134]

# Guardrails
RATE_LIMIT_WINDOW_S = 60
RATE_LIMIT_MAX = 6          # per session/IP per window
ACTION_TIMEOUT_S = 600     # hard cap on any single action
