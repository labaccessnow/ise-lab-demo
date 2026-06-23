"""Cisco Catalyst 9800-CL WLC RESTCONF client (Phase 5b — multi-vendor).

Mirrors devices.py: the backend holds the WLC admin credentials (SOPS `cisco_wlc`)
and mediates every call, so a visitor never sees a credential or reaches the WLC
directly. Read-only (GET) RESTCONF for the playground.

RESTCONF rides the IOS-XE HTTPS server (:443) under /restconf once `restconf` +
`ip http secure-server` are enabled on the WLC. Until then these ops return a clean
WLCError — the same graceful "turn it on" UX as ISE ERS being off.

The WLC's address is a deployment coordinate (config.WLC_HOST, from the gitignored
.env) so no enclave IP is ever committed.
"""
import base64
import json
import ssl
import urllib.error
import urllib.request

from . import config
from .secrets import load_secrets


class WLCError(Exception):
    """A WLC call failed in a way worth showing the visitor (not a 500)."""


_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _wlc():
    s = load_secrets()["cisco_wlc"]
    host = s.get("ip") or config.WLC_HOST
    return host, s["admin_user"], s["admin_password"]


def restconf_get(path: str):
    """GET a RESTCONF resource and return parsed JSON. Raises WLCError on failure.

    `path` is everything after /restconf, e.g. "/data/ietf-interfaces:interfaces".
    """
    host, user, pw = _wlc()
    url = f"https://{host}/restconf{path}"
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": f"Basic {auth}",
                 "Accept": "application/yang-data+json"},
    )
    try:
        with urllib.request.urlopen(req, context=_CTX, timeout=25) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt.strip() else {}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise WLCError(
                "WLC rejected auth — RESTCONF may be disabled, or the user lacks "
                "privilege-15 / RESTCONF authorization on the 9800-CL.")
        if e.code == 404:
            raise WLCError(
                f"WLC RESTCONF resource not found ({path}) — RESTCONF is up but that "
                "YANG path may differ on this IOS-XE version.")
        body_txt = e.read().decode()
        try:
            detail = json.loads(body_txt)
        except Exception:
            detail = body_txt[:300]
        raise WLCError(f"WLC returned {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise WLCError(
            f"WLC unreachable: {e.reason} — is RESTCONF (`restconf` + "
            "`ip http secure-server`) enabled on the 9800-CL?")
