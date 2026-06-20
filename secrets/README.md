# secrets

Project SOPS store, encrypted to this repo's **own** age key (separate from
`proxmox-automation`, per the "standalone project" goal).

- `secrets.sops.json` — encrypted secrets (committed).
- `age.key` — the private age key (**gitignored; never commit**).

Decrypt/run with, from the repo root:

```
export SOPS_AGE_KEY_FILE="$PWD/secrets/age.key"
```

## Keys the store must hold

| key | holds | source |
|---|---|---|
| `proxmox` | `user` / `token_name` / `token_value` — **enclave-scoped** API token | minted in Phase 0 (`pveum`), NOT the home-lab full-access token |
| `windc_demo` | `local_admin_password`, `dsrm_password` | migrate from proxmox-automation |
| `cisco_ise` | `cli_*`, `gui_*`, + (Phase 5a) `ers_user`/`ers_password` | migrate + extend |
| `cisco_wlc` | `admin_*`, `enable_secret`, `radius_secret` | migrate from proxmox-automation |
| `palo_alto` | `admin_*`, API key, bootstrap | new (Phase 2.6) |
| `portal_auth` | admin SSO + visitor demo-session signing secret | new (Phase 4/6) |

## Populate / migrate (done with the Phase-0 token mint)

```
# decrypt the home-lab store (uses ~/.config/sops/age/keys.txt)
sops -d ~/proxmox-automation/secrets/secrets.sops.json > /tmp/old.json
# select only the needed keys into /tmp/selected.json, then encrypt to THIS repo:
sops --encrypt --age <this-repo-recipient> /tmp/selected.json > secrets/secrets.sops.json
shred -u /tmp/old.json /tmp/selected.json
```

The `proxmox` key here should be the **enclave-scoped** token (Phase 0), not the
home-lab `james@pve!automation` full token — least privilege for the portal backend.
