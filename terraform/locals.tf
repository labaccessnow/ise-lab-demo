locals {
  # ---------------------------------------------------------------------------
  # Source EVE-NG qcow2 images, pre-staged on the Proxmox node (absolute paths).
  # `import_from` streams these into each VM's first disk on `terraform apply`.
  # ---------------------------------------------------------------------------
  images = {
    cat9kv    = "/mnt/pve/SSD4/cat9kvuadp-17.15.01-virtioa.qcow2"
    fmcv      = "/mnt/pve/SSD3/fmcv-7.7.0-89.qcow2"
    ftdv      = "/mnt/pve/SSD4/ftdv-7.7.0-89.qcow2"
    paloalto  = "/mnt/pve/SSD2/paloalto-11.2.5.qcow2"
    clearpass = "/mnt/pve/SSD1/clearpass-6.12.0.qcow2"
    c8000v    = "/mnt/pve/SSD4/c8000v-17.16.01a.qcow2"
    veos      = "/mnt/pve/SSD3/veos-4.33.1.1F.qcow2"
    arubacx   = "/mnt/pve/SSD3/arubacx-10.14.qcow2"
  }

  # ---------------------------------------------------------------------------
  # Raw per-platform specs (the demo enclave, on VLAN bridges
  # v1800=mgmt, v1801-1808=dot1x access, v1820/1821=FTD data, v1832/1833=PA data).
  # Optional keys (machine/vga/scsihw/boot_order, nic link_down/mac, disk
  # import/datastore) are filled with defaults by the normalizer below — keeping
  # this map readable. status: ok = configured + golden-snapshotted; pending = WIP.
  # ---------------------------------------------------------------------------
  _platforms = {
    # Cat9000v-UADP wired NAD — mgmt + 8 dot1x access ports.
    # LESSON: data ports MUST be e1000; on virtio the access ports never link.
    nad-sw = {
      vmid = 142, status = "ok", cores = 4, memory = 18432, store = "SSD4"
      nics = concat(
        [{ bridge = "v1800", model = "e1000" }],
        [for i in range(1, 9) : { bridge = format("v180%d", i), model = "e1000" }],
      )
      disks = [{ interface = "virtio0", size = 16, import = "cat9kv" }]
    }

    # Firepower Management Center 7.7.
    # LESSON: mgmt NIC MUST be e1000 (virtio link never comes up — same as PA).
    # LESSON: never hard-`qm stop` FMC — unclean shutdown triggers a multi-hour DB
    # check. First-boot DB-init is ~30 min; needs 32 GB RAM.
    fmcv = {
      vmid = 145, status = "pending", cores = 8, memory = 32768, store = "SSD3", vga = "std"
      nics  = [{ bridge = "v1800", model = "e1000" }]
      disks = [{ interface = "virtio0", size = 250, import = "fmcv" }]
    }

    # Firepower Threat Defense 7.7 (mgmt + diagnostic + inside/outside).
    ftdv = {
      vmid = 146, status = "pending", cores = 8, memory = 16384, store = "SSD4"
      nics = [
        { bridge = "v1800", model = "e1000" },  # mgmt (e1000 per the FMC/PA lesson)
        { bridge = "v1800", model = "virtio" }, # diagnostic
        { bridge = "v1821", model = "virtio" }, # data: inside
        { bridge = "v1820", model = "virtio" }, # data: outside
      ]
      disks = [{ interface = "virtio0", size = 50, import = "ftdv" }]
    }

    # Palo Alto VM-Series 11.2.
    # LESSON: e1000 (virtio mgmt won't link) AND in PAN-OS set the mgmt interface
    # `type static` — `set deviceconfig system ip-address` alone leaves it dhcp-client.
    # Dataplane NICs disconnected during bringup (mgmt-only) per PA community guidance.
    paloalto = {
      vmid = 147, status = "ok", cores = 4, memory = 9216, store = "SSD2"
      nics = [
        { bridge = "v1800", model = "e1000" },
        { bridge = "v1832", model = "e1000", link_down = true },
        { bridge = "v1833", model = "e1000", link_down = true },
      ]
      disks = [{ interface = "virtio0", size = 60, import = "paloalto" }]
    }

    # Aruba ClearPass CLABV 6.12.
    # LESSON: CLABV needs a 2nd ~400 GB disk at SCSI 0:1 as the primary boot image,
    # so use a SHARED controller (virtio-scsi-pci) and boot scsi1 first. (Post-install
    # boot still flaky on this hypervisor — switch candidate.)
    clearpass = {
      vmid = 148, status = "pending", cores = 8, memory = 16384, store = "SSD1", vga = "std"
      scsihw = "virtio-scsi-pci", boot_order = ["scsi1", "ide0"]
      nics = [{ bridge = "v1800", model = "virtio" }]
      disks = [
        { interface = "ide0", size = 40, import = "clearpass" },
        { interface = "scsi1", size = 400, datastore = "local-lvm" }, # blank data disk
      ]
    }

    # Catalyst 8000v 17.16 (IOS-XE automation showcase).
    # LESSON: hangs at "Booting the kernel" on this host regardless of vCPU/machine
    # type — pending a known-good image (17.12.x / CSR1000v). machine q35 retained.
    c8000v = {
      vmid = 150, status = "pending", cores = 4, memory = 4096, store = "SSD4"
      machine = "q35", vga = "std", scsihw = "virtio-scsi-pci", boot_order = ["scsi0"]
      nics  = [{ bridge = "v1800", model = "virtio" }]
      disks = [{ interface = "scsi0", size = 8, import = "c8000v" }]
    }

    # Arista vEOS 4.33 — eAPI. Configured cleanly over serial.
    veos = {
      vmid = 151, status = "ok", cores = 2, memory = 4096, store = "SSD3", vga = "std"
      nics  = [{ bridge = "v1800", model = "virtio" }]
      disks = [{ interface = "ide0", size = 5, import = "veos" }]
    }

    # Aruba CX 10.14 — REST. Configured cleanly over serial.
    arubacx = {
      vmid = 152, status = "ok", cores = 2, memory = 8192, store = "SSD3", vga = "std"
      scsihw = "virtio-scsi-single"
      nics  = [{ bridge = "v1800", model = "virtio" }]
      disks = [{ interface = "scsi0", size = 11, import = "arubacx" }]
    }
  }

  # ---------------------------------------------------------------------------
  # Normalize every platform to a uniform shape, so `for_each` (which requires a
  # homogeneous map) and the dynamic blocks type-check. Defaults for omitted keys
  # are applied here rather than cluttering the spec map above.
  # ---------------------------------------------------------------------------
  vms = {
    for name, p in local._platforms : name => {
      vmid       = p.vmid
      status     = p.status
      cores      = p.cores
      memory     = p.memory
      store      = p.store
      machine    = try(p.machine, null)
      vga        = try(p.vga, "std")
      scsihw     = try(p.scsihw, "virtio-scsi-single")
      boot_order = try(p.boot_order, [p.disks[0].interface])
      nics = [for n in p.nics : {
        bridge    = n.bridge
        model     = n.model
        link_down = try(n.link_down, false)
        mac       = try(n.mac, null)
      }]
      disks = [for d in p.disks : {
        interface = d.interface
        size      = d.size
        import    = try(d.import, null)
        datastore = try(d.datastore, p.store)
      }]
    }
  }
}
