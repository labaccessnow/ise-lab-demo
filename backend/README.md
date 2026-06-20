# backend — Tier 2 (privileged runner)

Holds the enclave-scoped Proxmox token + the SOPS key. Exposes **only** an
allowlisted set of actions to the Tier-1 portal. Never reachable by demo visitors.

## Layout
- `app/config.py` — enclave VMID allowlist, Proxmox target, guardrail limits
- `app/secrets.py` — decrypt the project SOPS store (project age key)
- `app/proxmox.py` — scoped-token Proxmox client (stdlib; status/snapshot/rollback)
- `app/actions.py` — allowlisted action registry + dispatch *(Phase 3, next)*
- `app/guardrails.py` — single-flight lock, rate limit, timeouts *(Phase 3, next)*
- `app/main.py` — FastAPI app *(Phase 3, next)*
- `manage_snapshots.py` — Phase 2 CLI: golden snapshot create / reset

## Phase 2 — golden snapshots (run from `backend/`)
```
python3 manage_snapshots.py status
python3 manage_snapshots.py create-golden   # when ISE/DC/WLC are all healthy
python3 manage_snapshots.py reset           # rollback to golden (~1-2 min)
```
Golden snapshots are taken **with RAM state**, so a reset restores a live,
already-healthy lab — no 45–65 min ISE re-init. `secrets.py` points SOPS at the
project age key automatically.
```
