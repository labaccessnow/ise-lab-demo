"""Best-effort Slack alerting for operational events (reset failure, lab offline).

Posts to the lab's #alerts incoming webhook (SOPS `slack_webhook_alerts`). Alerting
must NEVER break the caller — every failure is swallowed and logged, not raised.
"""
import json
import urllib.error
import urllib.request

from .secrets import load_secrets


def notify(text: str) -> bool:
    """POST a plain-text message to the #alerts webhook. Returns True on HTTP 200."""
    url = load_secrets().get("slack_webhook_alerts")
    # Validate up front: a malformed/scheme-less URL makes urllib raise a ValueError
    # that embeds the full URL — never let the webhook secret reach a log.
    if not (url and url.startswith("https://")):
        print("[alerts] slack_webhook_alerts missing or not https — skipping notify")
        return False
    try:
        req = urllib.request.Request(
            url, method="POST",
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError) as e:
        # Log only the exception TYPE — its message can contain the URL.
        print(f"[alerts] notify failed: {type(e).__name__}")
        return False
