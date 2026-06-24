# Site-specific coordinates come from a gitignored terraform.tfvars (see the
# .example). Committed defaults are placeholders so nothing real is published —
# same sanitization rule as the rest of the repo (no real IPs/secrets in git).

variable "pve_endpoint" {
  description = "Proxmox API endpoint URL"
  type        = string
  default     = "https://0.0.0.0:8006/"
}

variable "pve_api_token" {
  description = "Proxmox API token, format 'user@realm!tokenid=secret' (pool-scoped)"
  type        = string
  sensitive   = true
  default     = "iselab@pve!terraform=00000000-0000-0000-0000-000000000000"
}

variable "pve_node" {
  description = "Proxmox node name"
  type        = string
  default     = "pve"
}

variable "pool" {
  description = "Proxmox pool — the enclave blast-radius boundary"
  type        = string
  default     = "iselab"
}

variable "pve_insecure" {
  description = "Skip TLS verification (lab self-signed cert)"
  type        = bool
  default     = true
}

variable "pve_ssh_user" {
  description = "SSH user on the Proxmox node (needed for qcow2 import_from)"
  type        = string
  default     = "root"
}

variable "pve_ssh_agent" {
  description = "Use the local SSH agent to auth to the node"
  type        = bool
  default     = true
}
