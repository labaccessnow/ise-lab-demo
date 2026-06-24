# ise-lab-demo — Terraform: multi-vendor enclave VM provisioning layer.
# Codifies the Proxmox VMs that were previously stood up ad-hoc via `qm`.
# Pairs with: Ansible (in-guest config) + the Python backend (golden-snapshot reset).
terraform {
  required_version = ">= 1.5"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.66"
    }
  }
}
