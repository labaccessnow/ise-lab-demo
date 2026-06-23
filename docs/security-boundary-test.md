# Security boundary test — visitor isolation (Phase 6)

The lab's #1 requirement: a demo **visitor** has *website access only*. They must not be
able to pivot into internal infra, reach the internet from the enclave, read a credential,
or escape the action allowlist / the pixel-only desktop. This document is the adversarial
test that proves it — run it whenever the surface changes (new API ops, edge/auth changes).

`scripts/boundary_test.sh` automates the network + ufw + edge-SSO checks (A/D/F below).
The app-layer checks (B) run against the Tier-2 backend directly. Fill the **Result**
column on each run and date it in the log at the bottom.

## Threat model
- **Adversary:** an authenticated demo visitor (or a compromised enclave device).
- **Trust tiers:** Tier‑1 portal (DMZ, holds nothing) → Tier‑2 runner (trusted, holds the
  scoped Proxmox token + SOPS key + enclave SSH key) → Tier‑3 enclave (VLAN 1800, isolated).
- **Win condition for the defender:** every check below is green.

## How to run
```bash
# 1) network + ufw + edge (from a mgmt host that can reach the enclave, e.g. the controller):
#    set the internal targets in the gitignored .env first (ENCLAVE_JUMPBOX/ENCLAVE_ISE/
#    PROD_HOST/MGMT_HOST/BACKEND_HOST/GUAC_HOST), then:
./scripts/boundary_test.sh

# 2) app-layer guardrails: run section B ON the Tier-2 runner against localhost:8000.
```

## A — Network isolation  *(automated)*
Enforced by the OPNsense fw1/fw2 enclave block (`scripts/fw_enclave_iso_rule.py`) + the
mgt-router zone-FW. From the enclave jumpbox:

| Check | Expected | Result |
|-------|----------|--------|
| enclave → internet (`ping dns.google`) | blocked | |
| enclave → prod (`ping $PROD_HOST`) | blocked | |
| enclave → mgmt (`ping $MGMT_HOST`) | blocked | |
| enclave → intra-enclave (`ping $ENCLAVE_ISE`) | reachable | |
| mgmt → enclave (controller `ssh` jumpbox) | reachable (ops path) | |

## B — Backend allowlist + guardrails  *(run on the Tier-2 runner vs localhost:8000)*
Enforced in `backend/app/main.py:67-71` (lookup + `_authorized`), `actions.py:58-68`
(the ACTIONS allowlist — no free-form), `guardrails.py:28-55` (single-flight + rate limit).

```bash
B=http://127.0.0.1:8000
# unknown action -> 404 (only allowlisted ids exist)
curl -s -o /dev/null -w '%{http_code}\n' -XPOST $B/api/action/lab.bogus    -H 'X-Role: visitor' -H 'X-Session: t1'   # want 404
# visitor invoking an admin op -> 403
curl -s -o /dev/null -w '%{http_code}\n' -XPOST $B/api/action/lab.snapshot_golden -H 'X-Role: visitor' -H 'X-Session: t2'  # want 403
# param injection is inert (no interpreter; extra keys ignored)
curl -s -o /dev/null -w '%{http_code}\n' -XPOST $B/api/action/lab.status -H 'X-Role: visitor' -H 'X-Session: t3' -H 'Content-Type: application/json' -d '{"shell_cmd":"id"}'  # want 200, no shell run
# rate limit -> the 7th call in 60s is 429 (RATE_LIMIT_MAX=6)
for i in $(seq 1 7); do curl -s -o /dev/null -w '%{http_code} ' -XPOST $B/api/action/lab.status -H 'X-Role: visitor' -H 'X-Session: rl'; done; echo   # want ...200 429
# single-flight -> a 2nd concurrent mutating action is 409 (kick a long reset, then a 2nd)
```

| Check | Expected | Result |
|-------|----------|--------|
| unknown action | 404 | |
| visitor → admin op | 403 | |
| param injection inert | 200, no effect | |
| rate limit (7th/60s) | 429 | |
| single-flight (2nd concurrent mutate) | 409 | |

## C — Proxmox blast-radius guard
`backend/app/proxmox.py:40-42` asserts every VMID ∈ `ENCLAVE_VMS` (`config.py:36`); the
token is also pool-scoped (`infra/proxmox-scoped-token.md`).

| Check | Expected | Result |
|-------|----------|--------|
| a non-enclave VMID raises `ProxmoxError` (code review + a crafted call on Tier-2) | rejected | |
| scoped token lists only the `iselab` pool | only enclave VMs | |

## D — Tier-2 ufw locks  *(automated)*
| Check | Expected | Result |
|-------|----------|--------|
| backend `:8000` from a non-portal host | blocked | |
| guacamole `:8080` from a non-edge host | blocked | |

## E — Credential reach
The portal holds nothing (`frontend/portal.py` — no SOPS import); secrets live only on
Tier-2 (`backend/app/secrets.py`). Verify no op returns a secret and logs don't echo one.

| Check | Expected | Result |
|-------|----------|--------|
| `grep -ri sops/age/secret frontend/` on the portal VM | no hits | |
| every catalog op result + the SSE log scrubbed of creds | no secret in output | |

## F — Edge SSO  *(automated)*
| Check | Expected | Result |
|-------|----------|--------|
| `lab.labaccessnow.com` unauth | 302 → `id.labaccessnow.com` | |
| `desktop.labaccessnow.com` unauth | 302 → IdP | |

## G — Guacamole / jumpbox containment
`guacamole/docker-compose.yml:33-38` (header-auth, `REMOTE_USER` only via the edge); the
jumpbox is single-homed on the enclave and rolls back with `golden`.

| Check | Expected | Result |
|-------|----------|--------|
| `REMOTE_USER` spoof direct to `:8080` (not via edge) | blocked by ufw (see D) | |
| jumpbox has no route off the enclave (`ip route` on the jumpbox) | enclave-only | |
| a `lab.reset` rolls the jumpbox (134) back to golden | clean desktop | |

---

## Result log
| Date | Run by | Pass/Fail | Notes / gaps fixed |
|------|--------|-----------|--------------------|
| _pending first run_ | | | |
