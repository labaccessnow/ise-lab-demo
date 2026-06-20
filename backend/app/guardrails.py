"""Backend guardrails: single-flight lock + per-session rate limiting.

These bound what a visitor can do even after they're authorized for an action:
only one mutating action runs at a time (lab-wide), and each session is capped per
window. Timeouts on the actions themselves are enforced by the Proxmox client.
"""
import threading
import time
from collections import defaultdict, deque

from .config import RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_S

_lock = threading.Lock()                 # single-flight across the whole lab
_current = {"action": None, "since": None}
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


class Busy(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


def acquire(action_id: str):
    if not _lock.acquire(blocking=False):
        raise Busy(f"another action is already running: {_current['action']}")
    _current.update(action=action_id, since=time.monotonic())


def release():
    _current.update(action=None, since=None)
    try:
        _lock.release()
    except RuntimeError:
        pass


def current() -> dict:
    return dict(_current)


def rate_check(session: str):
    now = time.monotonic()
    with _hits_lock:
        dq = _hits[session]
        while dq and now - dq[0] > RATE_LIMIT_WINDOW_S:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_MAX:
            raise RateLimited(
                f"rate limit: max {RATE_LIMIT_MAX} actions per {RATE_LIMIT_WINDOW_S}s"
            )
        dq.append(now)
