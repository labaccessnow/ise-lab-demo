#!/usr/bin/env python3
"""Gate desktop.labaccessnow.com behind Authentik, mirroring lab-forward-auth.

Creates a `desktop-forward-auth` proxy provider + a `lab-desktop` application and
adds the provider to the embedded outpost, copying the working flows/cookie-domain
from the existing `lab-forward-auth` provider. Idempotent. Run on the demo-portal
VM (reads AUTHENTIK_API_TOKEN from ~/demo-portal/.env).
"""
import json
import os
import urllib.error
import urllib.request

TOKEN = None
for p in (os.path.expanduser("~/demo-portal/.env"), "/home/james/demo-portal/.env"):
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line.startswith("AUTHENTIK_API_TOKEN="):
                TOKEN = line.split("=", 1)[1].strip().strip('"')
        break
assert TOKEN, "AUTHENTIK_API_TOKEN not found in demo-portal/.env"

B = "http://localhost:9000/api/v3"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
EXT = "https://desktop.labaccessnow.com"


def req(method, path, data=None):
    r = urllib.request.Request(B + path, method=method, headers=H,
                               data=json.dumps(data).encode() if data else None)
    try:
        return json.load(urllib.request.urlopen(r, timeout=20))
    except urllib.error.HTTPError as e:
        print(method, path, "->", e.code, e.read().decode()[:300])
        raise


lab = [p for p in req("GET", "/providers/proxy/?search=lab-forward-auth")["results"]
       if p["name"] == "lab-forward-auth"][0]

ex = [p for p in req("GET", "/providers/proxy/?search=desktop-forward-auth")["results"]
      if p["name"] == "desktop-forward-auth"]
if ex:
    pk = ex[0]["pk"]
    print("provider exists pk", pk)
else:
    body = {k: lab[k] for k in ("authorization_flow", "authentication_flow",
            "invalidation_flow", "cookie_domain", "mode", "access_token_validity",
            "refresh_token_validity") if lab.get(k) is not None}
    body["name"] = "desktop-forward-auth"
    body["external_host"] = EXT
    pk = req("POST", "/providers/proxy/", body)["pk"]
    print("created provider pk", pk)

if not [a for a in req("GET", "/core/applications/?search=desktop")["results"]
        if a["slug"] == "lab-desktop"]:
    req("POST", "/core/applications/",
        {"name": "Lab Desktop", "slug": "lab-desktop", "provider": pk})
    print("app created: lab-desktop")
else:
    print("app exists: lab-desktop")

emb = [o for o in req("GET", "/outposts/instances/")["results"]
       if "embedded" in o["name"].lower()][0]
if pk not in emb["providers"]:
    req("PATCH", f"/outposts/instances/{emb['pk']}/",
        {"providers": emb["providers"] + [pk]})
    print("added to embedded outpost")
else:
    print("already in outpost")
print("DONE")
