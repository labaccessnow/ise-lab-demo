# One resource drives every platform via for_each over local.vms (normalized in
# locals.tf). Dynamic blocks absorb the per-vendor variation (1 NIC vs the NAD's 9,
# disconnected dataplane links, ClearPass's second disk) without duplicating it.
resource "proxmox_virtual_environment_vm" "platform" {
  for_each = local.vms

  vm_id       = each.value.vmid
  name        = each.key
  node_name   = var.pve_node
  pool_id     = var.pool
  description = "ise-lab multi-vendor platform — ${each.key} (status: ${each.value.status})"
  tags        = ["iselab", each.value.status]

  on_boot = false # enclave VMs are powered on demand by the control plane, not at host boot
  bios    = "seabios"
  machine = each.value.machine # q35 only where the image needs it; null = default

  operating_system { type = "l26" }

  cpu {
    cores = each.value.cores
    type  = "host"
  }

  memory {
    dedicated = each.value.memory
  }

  scsi_hardware = each.value.scsihw

  # Every EVE appliance gets a serial socket — several only speak over serial.
  serial_device {}

  vga {
    type = each.value.vga
  }

  boot_order = each.value.boot_order

  dynamic "network_device" {
    for_each = each.value.nics
    content {
      bridge       = network_device.value.bridge
      model        = network_device.value.model
      disconnected = network_device.value.link_down
      mac_address  = network_device.value.mac # null = auto; pin when importing existing VMs
    }
  }

  dynamic "disk" {
    for_each = { for d in each.value.disks : d.interface => d }
    content {
      datastore_id = disk.value.datastore
      interface    = disk.value.interface
      size         = disk.value.size
      file_format  = "qcow2"
      # First boot streams the EVE image in; a null import = a blank data disk.
      import_from = disk.value.import != null ? local.images[disk.value.import] : null
    }
  }

  lifecycle {
    # The Python control plane owns runtime state (power + golden snapshots).
    # Don't let Terraform fight it over whether the VM happens to be running.
    ignore_changes = [started]
  }
}
