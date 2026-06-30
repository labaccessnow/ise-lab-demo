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

## 2. Forward the authenticated identity to the portal (single-use session binding)
The portal binds a booking token to the Authentik-verified email (so a forwarded
`?session=` link is useless to anyone else). For that, the edge must capture the
email from the Authentik auth subrequest and pass it upstream as
`X-Forwarded-Email`, and MUST strip any client-supplied copy of that header so a
visitor can't spoof an identity. Mirror the existing `_999` auth-subrequest
wiring; add an `AUTH_REQUEST_SET` that captures the Authentik response header and
a `REVERSE_PROXY_HEADERS` that forwards it. Until this is in place the portal's
claim step fails closed (403), so the booking flow falls back to the current
presence/expiry validation — nothing breaks, the binding just isn't enforced yet.

After applying #2, wire the frontend to POST the `?session=` token to
`/api/session/claim` on load, and decide whether a valid bound session should be
REQUIRED for visitor actions (mandatory-booking) vs. the current "any
Authentik-authenticated user can drive the lab" model — a product decision.

## Policy defaults already coded (confirm / adjust)
- Identity source: Authentik email (`X-Forwarded-Email`), normalized (trim+lowercase).
- Match policy: strict — first claim must match the booking email; later claims
  must match the first claimant.
- Concurrency: kick-old — re-claim by the same identity invalidates the prior sid
  (one live session per booking).
