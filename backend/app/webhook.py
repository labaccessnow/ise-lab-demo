"""Cal.com booking webhook -> mint a time-boxed portal session for a self-service slot.

Cal.com fires BOOKING_CREATED with an HMAC-SHA256 signature (X-Cal-Signature-256)
over the raw body, keyed by the per-webhook secret (env CAL_WEBHOOK_SECRET). We
verify it, map the event type to a lab, mint a session that expires at the slot
end, and return the portal link. A later step (or the booking-side confirmation
email) hands that link to the booker. This service is only reachable from the
trusted side; Cal.com posts to it over the internal network.
"""
import hashlib
import hmac
import json
import os
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from . import emailer, sessions

router = APIRouter()

# Cal.com event-type slug -> lab id (today there is one lab; the map is the seam
# for more). Anything unmapped falls back to the default lab.
_LAB_BY_EVENT = {"self-service-lab": "ise-lab-demo", "ise-lab-demo": "ise-lab-demo"}
_DEFAULT_LAB = "ise-lab-demo"


def _verify(body: bytes, sig: str) -> bool:
    secret = os.environ.get("CAL_WEBHOOK_SECRET", "")
    if not secret:
        # Fail CLOSED: with no secret we cannot verify the signature, so reject
        # rather than accept arbitrary callers (an unsigned post would otherwise
        # mint a session + email a booking link to any attacker-chosen address).
        return False
    if not sig:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


@router.post("/api/webhook/cal-booking")
async def cal_booking(request: Request):
    body = await request.body()
    if not _verify(body, request.headers.get("X-Cal-Signature-256", "")):
        raise HTTPException(401, "bad signature")
    try:
        ev = json.loads(body)
    except Exception:
        raise HTTPException(400, "bad json")
    if ev.get("triggerEvent") != "BOOKING_CREATED":
        return {"ok": True, "ignored": ev.get("triggerEvent")}

    p = ev.get("payload", {}) or {}
    email = ((p.get("attendees") or [{}])[0] or {}).get("email", "")
    end = p.get("endTime") or p.get("end") or ""
    try:
        expires_at = datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp()
    except Exception:
        expires_at = time.time() + 3600  # fallback: 1h window
    slug = ((p.get("eventType") or {}).get("slug")) or ""
    lab_id = _LAB_BY_EVENT.get(slug, _DEFAULT_LAB)

    tok = sessions.mint(lab_id, email, expires_at)
    link = f"https://lab.labaccessnow.com/?session={tok}"
    emailed = False
    try:
        until = datetime.utcfromtimestamp(expires_at).strftime("%b %d %H:%M UTC")
        emailer.send_booking_link(email, link, until)
        emailed = True
    except Exception as e:  # best-effort: the token still exists if mail fails
        print(f"booking email to {email} failed: {e}")
    return {"ok": True, "lab": lab_id, "session": tok, "link": link, "emailed": emailed}
