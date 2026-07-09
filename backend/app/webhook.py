"""Cal.com booking webhook -> the lab's time-boxed access lifecycle.

Cal.com fires signed events (HMAC-SHA256 over the raw body in X-Cal-Signature-256,
keyed by the per-webhook secret, env CAL_WEBHOOK_SECRET). We verify and then:

- BOOKING_CREATED      mint a session for the slot window (starts_at -> endTime),
                       email the booker their portal link, alert #alerts.
- BOOKING_RESCHEDULED  move the existing session's window (the original emailed
                       link keeps working); mint fresh if we never saw it.
- BOOKING_CANCELLED    revoke the session(s) minted for that booking.

Every change nudges the lab-active group reconciler so Authentik-gated surfaces
(the streamed desktop) track the booking within seconds. This service is only
reachable from the trusted side; Cal.com posts to it over the internal network.
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from . import alerts, authentik_sync, emailer, sessions

router = APIRouter()

# Cal.com event-type slug -> lab id (today there is one lab; the map is the seam
# for more). Anything unmapped falls back to the default lab.
_LAB_BY_EVENT = {"self-service-lab": "ise-lab-demo", "ise-lab-demo": "ise-lab-demo"}
_DEFAULT_LAB = "ise-lab-demo"


def _secret() -> str:
    env = os.environ.get("CAL_WEBHOOK_SECRET", "")
    if env:
        return env
    try:  # deployment default: the lab SOPS store
        from .secrets import load_secrets
        return (load_secrets() or {}).get("calcom_webhook_secret", "") or ""
    except Exception:
        return ""


def _verify(body: bytes, sig: str) -> bool:
    secret = _secret()
    if not secret:
        # Fail CLOSED: with no secret we cannot verify the signature, so reject
        # rather than accept arbitrary callers (an unsigned post would otherwise
        # mint a session + email a booking link to any attacker-chosen address).
        return False
    if not sig:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _ts(iso: str, fallback: float) -> float:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).timestamp()
    except Exception:
        return fallback


def _fmt(ts: float) -> str:
    return datetime.utcfromtimestamp(ts).strftime("%b %d %H:%M UTC")


def _nudge_sync() -> None:
    """Reconcile lab-active off-thread so group membership tracks a booking
    change within seconds, not the next periodic tick. Never raises."""
    try:
        asyncio.get_running_loop().run_in_executor(
            None, lambda: authentik_sync.reconcile(sessions.active_emails()))
    except Exception as e:
        print(f"[webhook] sync nudge failed: {type(e).__name__}")


@router.post("/api/webhook/cal-booking")
async def cal_booking(request: Request):
    body = await request.body()
    if not _verify(body, request.headers.get("X-Cal-Signature-256", "")):
        raise HTTPException(401, "bad signature")
    try:
        ev = json.loads(body)
    except Exception:
        raise HTTPException(400, "bad json")
    trigger = ev.get("triggerEvent")
    p = ev.get("payload", {}) or {}
    uid = p.get("uid") or ""

    if trigger == "BOOKING_CANCELLED":
        revoked = sessions.drop_uid(uid)
        if revoked:
            await asyncio.to_thread(
                alerts.notify, "📅 Lab booking cancelled — its session was revoked.")
            _nudge_sync()
        return {"ok": True, "revoked": revoked}

    if trigger not in ("BOOKING_CREATED", "BOOKING_RESCHEDULED"):
        return {"ok": True, "ignored": trigger}

    email = ((p.get("attendees") or [{}])[0] or {}).get("email", "")
    now = time.time()
    starts_at = _ts(p.get("startTime") or p.get("start") or "", now)
    expires_at = _ts(p.get("endTime") or p.get("end") or "", now + 3600)
    slug = ((p.get("eventType") or {}).get("slug")) or p.get("type") or ""
    lab_id = _LAB_BY_EVENT.get(slug, _DEFAULT_LAB)
    window = f"{_fmt(starts_at)} → {_fmt(expires_at)}"

    # A reschedule moves the existing session's window and re-keys it to the new
    # booking uid; if we never saw the original, fall through and mint fresh.
    if trigger == "BOOKING_RESCHEDULED":
        old_uid = p.get("rescheduleUid") or uid
        if sessions.reschedule_uid(old_uid, starts_at, expires_at, new_uid=uid):
            await asyncio.to_thread(
                alerts.notify, f"📅 Lab booking rescheduled: {email} — {window}")
            _nudge_sync()
            return {"ok": True, "rescheduled": True}

    tok = sessions.mint(lab_id, email, expires_at, starts_at=starts_at, uid=uid)
    link = f"https://lab.labaccessnow.com/?session={tok}"
    emailed = False
    try:
        await asyncio.to_thread(emailer.send_booking_link, email, link, _fmt(expires_at))
        emailed = True
    except Exception as e:  # best-effort: the token still exists if mail fails
        print(f"booking email to {email} failed: {e}")
    await asyncio.to_thread(
        alerts.notify, f"📅 Lab slot booked (auto-granted): {email} — {window} [{lab_id}]")
    _nudge_sync()
    return {"ok": True, "lab": lab_id, "session": tok, "link": link, "emailed": emailed}
