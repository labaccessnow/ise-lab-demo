# Lab desktop gateway (Apache Guacamole)

Browser RDP into the enclave **jumpbox** so a visitor can drive the real device
GUIs (Cisco ISE, the WLC, the DC) without their machine ever getting a route into
the lab. Guacamole streams **pixels, not packets**; the jumpbox itself is
enclave-isolated, so the blast radius is a throwaway desktop that resets with the
lab.

```
visitor → desktop.labaccessnow.com (edge, Authentik-gated, sets REMOTE_USER)
        → Guacamole (this stack, trusted tier)  → guacd → jumpbox 0.0.0.0:3389
```

## Deploy (on the trusted Tier-2 host)
```bash
echo "DB_PASSWORD=$(openssl rand -hex 16)" > .env
docker run --rm guacamole/guacamole /opt/guacamole/bin/initdb.sh --postgresql > initdb/001-schema.sql
sudo docker compose up -d
```
Then seed the `Enterprise Lab Desktop` RDP connection (host `0.0.0.0`, user `james`,
password from SOPS `jumpbox`) and a limited `demo` user granted only that
connection — see the project docs.

## SSO
`HEADER_ENABLED=true` + `HTTP_AUTH_HEADER=REMOTE_USER`: the edge forward-auths the
visitor against Authentik, then passes a fixed `REMOTE_USER: demo` header.
Guacamole trusts it (no second login). `:8080` is **ufw-locked to the edge only**,
so the header can't be spoofed by reaching Guacamole directly.
