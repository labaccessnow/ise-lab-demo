# Edge (BunkerWeb) config the lab portal depends on

The public edge is BunkerWeb (all-in-one). Per-vhost settings live as
`lab.labaccessnow.com_*` keys in the edge's `docker-compose.yml`. Two settings
the ISE-lab portal needs are NOT yet applied (they change the shared edge that
fronts every public site, so they are deliberately operator-applied, not
automated). Apply both, then `docker compose up -d` to recreate the edge
container (brief blip for all sites).

Use `0.0.0.0` placeholders here; the real hostnames are obvious from context.

## 1. Long read timeout for the synchronous reset
A `lab.reset` blocks until the lab is rolled back AND verified healthy
(~2–3 min, hard-capped at 240s by the backend). BunkerWeb's
`REVERSE_PROXY_READ_TIMEOUT` defaults to **60s**, so a reset would 504 at the
edge. Set it above the chain (edge 330 > portal proxy 300 > backend 240):

```yaml
lab.labaccessnow.com_REVERSE_PROXY_READ_TIMEOUT: "330s"
```

## 2. Forward the authenticated identity to the portal (APPLIED)
The portal trusts `X-Forwarded-Email` / `X-Forwarded-Groups` for identity, role
(admin group) and the booking gate, so the edge must set them from the Authentik
auth subrequest — and, critically, override any client-supplied copies (nginx's
`proxy_set_header` does both at once). Alongside the existing `_999`
auth-subrequest wiring:

```yaml
lab.labaccessnow.com_REVERSE_PROXY_AUTH_REQUEST_SET: "$$auth_email $$upstream_http_x_authentik_email;$$auth_groups $$upstream_http_x_authentik_groups"
lab.labaccessnow.com_REVERSE_PROXY_HEADERS: "X-Forwarded-Email $$auth_email;X-Forwarded-Groups $$auth_groups"
```

Two companion pieces this relies on:
- **The portal host firewalls :8080 to the edge's IP only.** Anything else on
  the DMZ segment could otherwise skip the edge and hand the portal spoofed
  identity headers.
- **Access model (decided):** any authenticated user may browse the portal
  (reads); MUTATING actions require a booking window that is active right now,
  with two Authentik-group overrides — the admin group (`lab-admins`) and the
  tester group (`lab-approved`). The backend enforces this; the streamed
  desktop is enforced by Authentik itself via the reconciler-managed
  `lab-active` group (members == identities with a live booked session).

## Policy defaults already coded (confirm / adjust)
- Identity source: Authentik email (`X-Forwarded-Email`), normalized (trim+lowercase).
- Match policy: strict — first claim must match the booking email; later claims
  must match the first claimant.
- Concurrency: kick-old — re-claim by the same identity invalidates the prior sid
  (one live session per booking).
