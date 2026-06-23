"""The API playground catalog (Phase 5b).

The allowlisted device operations a visitor may run *through the portal*. Reads are
safe; writes act only on snapshot-recoverable objects, so a lab reset undoes them.
Each entry becomes an allowlisted Action (see actions.py) — there is no free-form
API access; a visitor can only invoke what's listed here.
"""
import re

from . import config, devices, wlc
from .secrets import load_secrets


def _read(method, path):
    return lambda params: devices.ise_call(method, path)


def _create_endpoint(params):
    mac = str(params.get("mac", "")).strip().upper()
    if not re.fullmatch(r"[0-9A-F]{2}([:-][0-9A-F]{2}){5}", mac):
        raise devices.DeviceError("mac must look like AA:BB:CC:DD:EE:FF")
    body = {"ERSEndPoint": {"name": mac, "mac": mac,
                            "description": "demo endpoint via the API playground"}}
    return devices.ise_call("POST", "/ers/config/endpoint", body)


def _wlc_read(path):
    return lambda params: wlc.restconf_get(path)


def _add_nad(params):
    """Register the WLC as an ISE network device (RADIUS NAD). The shared secret
    is read from the store server-side — never accepted from the caller."""
    name = str(params.get("name", "")).strip() or "wlc-demo"
    secret = load_secrets()["cisco_wlc"]["radius_secret"]
    body = {"NetworkDevice": {
        "name": name,
        "description": "demo WLC registered via the API playground",
        "profileName": "Cisco",
        "coaPort": 1700,
        "NetworkDeviceIPList": [{"ipaddress": config.WLC_HOST, "mask": 32}],
        "authenticationSettings": {"radiusSharedSecret": secret, "enableKeyWrap": False},
    }}
    return devices.ise_call("POST", "/ers/config/networkdevice", body)


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

    # --- More ISE OpenAPI reads (work once OpenAPI is on — already enabled) ---
    "ise.policy_sets": {
        "label": "Network-access policy sets", "role": "admin", "mutating": False,
        "summary": "List network-access policy sets (OpenAPI)",
        "params": [], "call": _read("GET", "/api/v1/policy/network-access/policy-set"),
    },
    "ise.authz_profiles": {
        "label": "Authorization profiles", "role": "visitor", "mutating": False,
        "summary": "List authorization profiles, e.g. PermitAccess (OpenAPI)",
        "params": [], "call": _read("GET", "/api/v1/policy/network-access/authorization-profiles"),
    },
    "ise.trusted_certs": {
        "label": "Trusted certificates", "role": "admin", "mutating": False,
        "summary": "List the ISE trusted-certificate store (OpenAPI)",
        "params": [], "call": _read("GET", "/api/v1/certs/trusted-certificate"),
    },

    # --- More ISE ERS reads (need ERS :9060 enabled) ---
    "ise.profiling_rules": {
        "label": "Endpoint profiling policies", "role": "visitor", "mutating": False,
        "summary": "List endpoint profiling policies (ERS)",
        "params": [], "call": _read("GET", "/ers/config/profilerprofile?size=20"),
    },
    "ise.allowed_protocols": {
        "label": "Allowed protocol services", "role": "admin", "mutating": False,
        "summary": "List allowed-protocols services, e.g. Default Network Access (ERS)",
        "params": [], "call": _read("GET", "/ers/config/allowedprotocols"),
    },

    # --- ERS write: register the WLC as a RADIUS NAD (admin; reset-recoverable) ---
    "ise.add_nad": {
        "label": "Register the WLC as a NAD", "role": "admin", "mutating": True,
        "summary": "Add the 9800-CL to ISE as a RADIUS network device — a reset wipes it",
        "params": [{"name": "name", "label": "Device name", "required": False,
                    "example": "wlc-demo"}],
        "call": _add_nad,
    },

    # --- WLC 9800-CL RESTCONF reads (multi-vendor; need RESTCONF on the WLC) ---
    "wlc.version": {
        "label": "WLC IOS-XE version", "role": "visitor", "mutating": False,
        "summary": "Show the WLC software version (RESTCONF)",
        "params": [], "call": _wlc_read("/data/Cisco-IOS-XE-native:native/version"),
    },
    "wlc.interfaces": {
        "label": "WLC interfaces", "role": "visitor", "mutating": False,
        "summary": "List the WLC interfaces (RESTCONF, IETF model)",
        "params": [], "call": _wlc_read("/data/ietf-interfaces:interfaces"),
    },
    "wlc.wlans": {
        "label": "WLC WLANs", "role": "visitor", "mutating": False,
        "summary": "List the WLANs configured on the 9800-CL (RESTCONF)",
        "params": [], "call": _wlc_read("/data/Cisco-IOS-XE-wireless-wlan-cfg:wlan-cfg-data"),
    },
}


def public():
    """Catalog metadata for the playground UI (no callables)."""
    return [{"id": k, "label": v["label"], "summary": v["summary"],
             "mutating": v["mutating"], "role": v["role"], "params": v["params"]}
            for k, v in CATALOG.items()]
