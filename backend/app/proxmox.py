"""Minimal Proxmox VE API client using the enclave-scoped token (stdlib only).

Only the operations the demo needs: read status/snapshots, snapshot, rollback,
start/stop. Every VM-targeting call asserts the VMID is in the enclave allowlist.
"""
import json
import ssl
import urllib.parse
import urllib.request

from .config import ENCLAVE_VMS, POOL, PROXMOX_HOST, PROXMOX_NODE, PROXMOX_PORT
from .secrets import load_secrets

_CTX = ssl._create_unverified_context()  # demo enclave; PVE uses a self-signed cert


class ProxmoxError(RuntimeError):
    pass


class Proxmox:
    def __init__(self):
        p = load_secrets()["proxmox"]
        self._auth = f"PVEAPIToken={p['user']}!{p['token_name']}={p['token_value']}"
        self._base = f"https://{PROXMOX_HOST}:{PROXMOX_PORT}/api2/json"

    def _req(self, method: str, path: str, data: dict | None = None):
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(
            self._base + path, data=body, method=method,
            headers={"Authorization": self._auth},
        )
        try:
            with urllib.request.urlopen(req, context=_CTX, timeout=30) as r:
                return json.load(r).get("data")
        except urllib.error.HTTPError as e:
            raise ProxmoxError(f"{method} {path} -> HTTP {e.code} {e.reason}") from None

    @staticmethod
    def _guard(vmid: int):
        if vmid not in ENCLAVE_VMS:
            raise ProxmoxError(f"refusing to act on VM {vmid}: not in the enclave allowlist")

    # --- reads ---
    def pool_members(self) -> list[dict]:
        data = self._req("GET", f"/pools/{POOL}")
        return [m for m in data.get("members", []) if m.get("type") == "qemu"]

    def vm_status(self, vmid: int) -> dict:
        self._guard(vmid)
        return self._req("GET", f"/nodes/{PROXMOX_NODE}/qemu/{vmid}/status/current")

    def list_snapshots(self, vmid: int) -> list[dict]:
        self._guard(vmid)
        return self._req("GET", f"/nodes/{PROXMOX_NODE}/qemu/{vmid}/snapshot") or []

    # --- writes ---
    def snapshot(self, vmid: int, name: str, description: str = "", vmstate: bool = True) -> str:
        self._guard(vmid)
        return self._req(
            "POST", f"/nodes/{PROXMOX_NODE}/qemu/{vmid}/snapshot",
            {"snapname": name, "description": description, "vmstate": 1 if vmstate else 0},
        )

    def rollback(self, vmid: int, name: str) -> str:
        self._guard(vmid)
        return self._req("POST", f"/nodes/{PROXMOX_NODE}/qemu/{vmid}/snapshot/{name}/rollback")

    def start(self, vmid: int) -> str:
        self._guard(vmid)
        return self._req("POST", f"/nodes/{PROXMOX_NODE}/qemu/{vmid}/status/start")

    def task_status(self, upid: str) -> dict:
        return self._req("GET", f"/nodes/{PROXMOX_NODE}/tasks/{urllib.parse.quote(upid, safe='')}/status")
