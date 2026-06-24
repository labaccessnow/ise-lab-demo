# Proxmox provider (bpg). Auth via an API token scoped to the `iselab` pool —
# the same blast-radius boundary the Python backend enforces. SSH to the node is
# required for `import_from` (streaming the EVE qcow2 into a new VM disk).
provider "proxmox" {
  endpoint  = var.pve_endpoint           # e.g. https://0.0.0.0:8006/
  api_token = var.pve_api_token          # "iselab@pve!terraform=<uuid>"
  insecure  = var.pve_insecure           # lab uses a self-signed cert

  ssh {
    agent    = var.pve_ssh_agent
    username = var.pve_ssh_user
  }
}
