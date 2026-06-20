"""The API playground catalog (Phase 5b).

The allowlisted device operations a visitor may run *through the portal*. Reads are
safe; writes act only on snapshot-recoverable objects, so a lab reset undoes them.
Each entry becomes an allowlisted Action (see actions.py) — there is no free-form
API access; a visitor can only invoke what's listed here.
"""
import re

from . import devices


def _read(method, path):
    return lambda params: devices.ise_call(method, path)


def _create_endpoint(params):
    mac = str(params.get("mac", "")).strip().upper()
    if not re.fullmatch(r"[0-9A-F]{2}([:-][0-9A-F]{2}){5}", mac):
        raise devices.DeviceError("mac must look like AA:BB:CC:DD:EE:FF")
    body = {"ERSEndPoint": {"name": mac, "mac": mac,
                            "description": "demo endpoint via the API playground"}}
    return devices.ise_call("POST", "/ers/config/endpoint", body)


# id -> {label, summary, role, mutating, params, call(params)->result}
CATALOG = {
    "ise.deployment": {
        "label": "ISE deployment nodes", "role": "visitor", "mutating": False,
        "summary": "Show the ISE node(s) + personas (OpenAPI)",
        "params": [], "call": _read("GET", "/api/v1/deployment/node"),
    },
    "ise.endpoint_groups": {
        "label": "Endpoint identity groups", "role": "visitor", "mutating": False,
        "summary": "List endpoint identity groups (ERS)",
        "params": [], "call": _read("GET", "/ers/config/endpointgroup?size=100"),
    },
    "ise.endpoints": {
        "label": "Registered endpoints", "role": "visitor", "mutating": False,
        "summary": "List registered endpoints (ERS)",
        "params": [], "call": _read("GET", "/ers/config/endpoint?size=50"),
    },
    "ise.network_devices": {
        "label": "Network devices (NADs)", "role": "visitor", "mutating": False,
        "summary": "List network access devices (ERS)",
        "params": [], "call": _read("GET", "/ers/config/networkdevice?size=100"),
    },
    "ise.identity_groups": {
        "label": "User identity groups", "role": "visitor", "mutating": False,
        "summary": "List user identity groups (ERS)",
        "params": [], "call": _read("GET", "/ers/config/identitygroup?size=100"),
    },
    "ise.create_endpoint": {
        "label": "Register a test endpoint", "role": "visitor", "mutating": True,
        "summary": "Create an endpoint by MAC — a lab reset wipes it",
        "params": [{"name": "mac", "label": "MAC address", "required": True,
                    "example": "AA:BB:CC:00:11:22"}],
        "call": _create_endpoint,
    },
}


def public():
    """Catalog metadata for the playground UI (no callables)."""
    return [{"id": k, "label": v["label"], "summary": v["summary"],
             "mutating": v["mutating"], "role": v["role"], "params": v["params"]}
            for k, v in CATALOG.items()]
