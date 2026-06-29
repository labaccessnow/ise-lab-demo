"""Device API clients for the playground (Phase 5b).

The backend holds the device credentials (SOPS) and mediates every call — a visitor
never sees a credential and never reaches a device directly. Read-mostly; the
catalog limits writes to snapshot-recoverable objects that a reset wipes.

Today: Cisco ISE (OpenAPI on 443 for `/api/*`, ERS on 9060 for `/ers/*`).
"""
import base64
import json
import ssl
import urllib.error
import urllib.request

from .secrets import load_secrets


class DeviceError(Exception):
    """A device call failed in a way worth showing the visitor (not a 500)."""


_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # ISE 302-redirects API calls to /admin/ when the API service is OFF; we must
    # see that redirect rather than silently following it to the GUI login page.
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_CTX))


def _ise_creds():
    s = load_secrets()["cisco_ise"]
    # `ip` is stored with a CIDR suffix (e.g. 0.0.0.0/24); strip it so the URL host
    # is just the address — otherwise the "/24" lands in the path and ISE
    # 302-redirects the unknown path to /admin/ (mistaken for "API disabled").
    return s["ip"].split("/")[0], s["gui_user"], s["gui_password"]


def ise_call(method: str, path: str, body=None):
    """Call the ISE API and return parsed JSON. Raises DeviceError on failure."""
    ip, user, pw = _ise_creds()
    base = f"https://{ip}" if path.startswith("/api") else f"https://{ip}:9060"
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req = urllib.request.Request(
        base + path, method=method,
        data=(json.dumps(body).encode() if body is not None else None),
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=25) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt.strip() else {}
    except urllib.error.HTTPError as e:
        if e.code in (301, 302):
            raise DeviceError(
                "ISE ERS/OpenAPI is not enabled — turn it on in "
                "Administration → System → Settings → API Settings.")
        body_txt = e.read().decode()
        try:
            detail = json.loads(body_txt)
        except Exception:
            detail = body_txt[:300]
        raise DeviceError(f"ISE returned {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise DeviceError(f"ISE unreachable: {e.reason}")
