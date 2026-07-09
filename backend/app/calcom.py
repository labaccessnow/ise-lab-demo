"""Server-side Cal.com booking (the booking BFF).

The portal books the self-service lab ON BEHALF of the edge-verified identity, so
the attendee email is always the authenticated SSO email — never a client-supplied
value. This closes the confused-deputy gap: Cal.com's own booking form takes a
free-text attendee email, so a signed-in visitor could otherwise reserve the lab
under someone else's address. Here the caller never gets to set the email.

We call Cal.com's internal booking endpoint directly on the DMZ, bypassing the
public forward-auth gate (that gate is for browsers; this is trusted server-side).
The REST API app (/api/v1) isn't deployed on this instance, so /api/book/event —
the same endpoint the Cal.com booking page uses — is the integration point.
"""
import json
import os
import time
import urllib.error
import urllib.request

CALCOM_URL = os.environ.get("CALCOM_INTERNAL_URL", "http://cal.internal:3000").rstrip("/")
EVENT_ID = int(os.environ.get("CALCOM_LAB_EVENT_ID", "2"))
EVENT_SLUG = os.environ.get("CALCOM_LAB_EVENT_SLUG", "self-service-lab")
EVENT_USER = os.environ.get("CALCOM_LAB_EVENT_USER", "labaccessnow")
EVENT_TZ = os.environ.get("CALCOM_LAB_TZ", "America/New_York")


class BookingError(RuntimeError):
    def __init__(self, msg: str, conflict: bool = False):
        super().__init__(msg)
        self.conflict = conflict


def next_slot_iso(within: int = 300) -> str:
    """Next `within`-second boundary from now, as a UTC ISO instant — the default
    'start now' time. 5-min granularity keeps the start just ahead of 'now'."""
    s = ((int(time.time()) // within) + 1) * within
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(s))


def book(email: str, name: str, start_iso: str) -> dict:
    """Create a booking for `email` at `start_iso`. The email is authoritative
    (the verified identity); `name` is cosmetic. Raises BookingError(conflict=True)
    when the slot is taken/unavailable so the caller can say 'pick another time'."""
    payload = {
        "eventTypeId": EVENT_ID,
        "eventTypeSlug": EVENT_SLUG,
        "start": start_iso,
        "timeZone": EVENT_TZ,
        "language": "en",
        "user": EVENT_USER,
        "responses": {"name": name or email.split("@")[0], "email": email, "guests": []},
        "metadata": {"bookedVia": "portal-bff"},
    }
    req = urllib.request.Request(
        CALCOM_URL + "/api/book/event",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        conflict = e.code == 409 or "no_available" in body or "already" in body
        # Don't surface Cal.com's raw body (may echo internals); classify only.
        raise BookingError("slot unavailable" if conflict else f"cal http {e.code}",
                           conflict=conflict)
    except (urllib.error.URLError, OSError) as e:
        raise BookingError(f"cal unreachable: {type(e).__name__}")
    return {"uid": d.get("uid"), "start": d.get("startTime") or start_iso,
            "end": d.get("endTime")}
