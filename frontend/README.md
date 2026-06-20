# Portal (Tier 1)

The visitor-facing web portal. Serves the static frontend and proxies *allowlisted*
action requests to the trusted Tier-2 [`backend`](../backend). It holds **nothing** —
no Proxmox token, no SOPS key, no route to the lab network — so a compromised portal
can only ask for actions that already exist, at the `visitor` role.

```
browser ──▶ portal (this, DMZ, holds nothing) ──▶ backend (trusted, holds secrets) ──▶ enclave
            serves static + sets X-Role             enforces allowlist + guardrails
```

## Run

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
BACKEND_URL=http://<tier2-backend>:8000 uvicorn portal:app --host 0.0.0.0 --port 8080
```

- `static/` — the frontend (no build step; vanilla HTML/CSS/JS).
- `portal.py` — the BFF: `/api/actions`, `/api/action/{id}`, `/healthz`; everything else is static.
- Role is `visitor` by default. A real auth layer (Authelia / the booking demo-session
  token) sits **in front** and may raise the role via a trusted server-side header —
  never from the client.

## Status

MVP: lab **state** + one-click **reset**. The API playground (the `catalog/`) and the
admin console are later phases.
