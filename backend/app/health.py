"""Post-reset health verification for the enclave.

A reset is only "good" when every advertised device actually answers — a vmstate
rollback can still land a device in a bad state (host hiccup, partial restore). We
verify after every reset; on persistent failure the lab is taken offline + alerted
so a visitor never drives a half-broken lab.
"""
import socket

from . import devices
from .config import HEALTH_TARGETS


def _tcp(host: str, port: int, timeout: float = 4.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ise_api_ok() -> tuple[bool, str]:
    """Deeper than TCP: ISE actually serves the API a visitor will use."""
    try:
        r = devices.ise_call("GET", "/api/v1/deployment/node")
        nodes = r.get("response", []) if isinstance(r, dict) else []
        connected = any(n.get("nodeStatus") == "Connected" for n in nodes)
        return (connected, "node Connected" if connected else f"node not Connected: {nodes}")
    except devices.DeviceError as e:
        return (False, str(e))


def check_lab() -> dict:
    """One pass over every health target. Returns {ok, checks, unhealthy}."""
    checks = []
    for name, host, port in HEALTH_TARGETS:
        ok = _tcp(host, port)
        detail = "" if ok else "no TCP answer"
        # ISE OpenAPI port: confirm it actually serves the API, not just TCP-open.
        if name == "ise1-https" and ok:
            api_ok, api_detail = _ise_api_ok()
            ok, detail = api_ok, api_detail
        checks.append({"name": name, "host": host, "port": port, "ok": ok, "detail": detail})
    unhealthy = [c for c in checks if not c["ok"]]
    return {"ok": not unhealthy, "checks": checks, "unhealthy": unhealthy}
