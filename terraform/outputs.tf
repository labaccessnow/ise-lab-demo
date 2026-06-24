output "platform_vmids" {
  description = "VMID for each platform (matches ENCLAVE_VMS in the backend config)."
  value       = { for k, v in local.vms : k => v.vmid }
}

output "reset_baseline_ready" {
  description = "Platforms eligible for the golden-snapshot reset baseline (status = ok)."
  value       = sort([for k, v in local.vms : k if v.status == "ok"])
}

output "pending_platforms" {
  description = "Platforms whose build is not yet finished (no golden snapshot)."
  value       = sort([for k, v in local.vms : k if v.status == "pending"])
}
