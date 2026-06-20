"""ise-lab-demo backend (Tier 2): the privileged automation runner.

Holds the scoped Proxmox token + SOPS key; exposes only an allowlisted set of
actions to the Tier-1 portal. Never reachable directly by demo visitors.
"""
