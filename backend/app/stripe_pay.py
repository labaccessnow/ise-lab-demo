"""Stripe test-mode checkout + webhook verification via the REST API (stdlib only).

Keys live in the lab SOPS store under `stripe` (pk_test / sk_test / whsec). Checkout
uses dynamic per-hour pricing so "buy N hours" maps cleanly to N credit-hours; the
hosted Stripe page collects the (test) card. The webhook is signature-verified with
whsec before any credit is granted.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .secrets import load_secrets

CREDIT_PRICE_PER_HOUR_CENTS = int(os.environ.get("CREDIT_PRICE_PER_HOUR_CENTS", "500"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://lab.labaccessnow.com").rstrip("/")
_API = "https://api.stripe.com/v1"


class StripeError(RuntimeError):
    pass


def _cfg() -> dict:
    return (load_secrets() or {}).get("stripe") or {}


def configured() -> bool:
    return bool(_cfg().get("sk_test"))


def _post(path: str, form: list) -> dict:
    sk = _cfg().get("sk_test")
    if not sk:
        raise StripeError("stripe not configured")
    req = urllib.request.Request(
        _API + path, data=urllib.parse.urlencode(form).encode(),
        headers={"Authorization": f"Bearer {sk}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise StripeError(f"stripe {path} -> {e.code}: {e.read().decode()[:160]}")
    except (urllib.error.URLError, OSError) as e:
        raise StripeError(f"stripe unreachable: {type(e).__name__}")


def create_checkout_session(email: str, hours: int) -> dict:
    """A hosted test-mode Checkout Session to buy `hours` of lab time. The buyer's
    identity rides in client_reference_id + metadata so the webhook credits the
    right account. Returns {url, id}."""
    hours = max(1, min(int(hours or 1), 8))
    form = [
        ("mode", "payment"),
        ("customer_email", email),
        ("client_reference_id", email),
        ("success_url", f"{PUBLIC_BASE_URL}/?checkout=success"),
        ("cancel_url", f"{PUBLIC_BASE_URL}/?checkout=cancel"),
        ("line_items[0][quantity]", str(hours)),
        ("line_items[0][price_data][currency]", "usd"),
        ("line_items[0][price_data][unit_amount]", str(CREDIT_PRICE_PER_HOUR_CENTS)),
        ("line_items[0][price_data][product_data][name]", "ISE Lab — 1 lab hour"),
        ("metadata[email]", email),
        ("metadata[hours]", str(hours)),
    ]
    d = _post("/checkout/sessions", form)
    return {"url": d.get("url"), "id": d.get("id")}


def create_webhook_endpoint(url: str) -> dict:
    """Register (test-mode) a webhook endpoint for checkout.session.completed and
    return its signing secret. Used once to wire our public URL."""
    d = _post("/webhook_endpoints", [
        ("url", url),
        ("enabled_events[]", "checkout.session.completed"),
        ("description", "ise-lab-demo credits"),
    ])
    return {"id": d.get("id"), "secret": d.get("secret")}


def verify_event(body: bytes, sig_header: str) -> dict | None:
    """Verify a Stripe-Signature header (t=..,v1=..) against whsec and return the
    event dict, or None if it doesn't check out. Rejects >5-min-old timestamps
    (replay protection)."""
    whsec = _cfg().get("whsec")
    if not whsec or not sig_header:
        return None
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    t, v1 = parts.get("t"), parts.get("v1")
    if not (t and v1):
        return None
    expected = hmac.new(whsec.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, v1):
        return None
    try:
        if abs(time.time() - int(t)) > 300:
            return None
    except ValueError:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None
