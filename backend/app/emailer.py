"""Send the booking handoff email — the booker's portal link — via booking@.

On a self-service booking the backend mints a time-boxed session and mails the
booker their link. Creds come from SOPS (smtp). Best-effort: a send failure is
logged, never fatal — the token still exists and the link still works.
"""
import smtplib
import ssl
from email.message import EmailMessage

from .secrets import load_secrets


def send_booking_link(to: str, link: str, until: str = "") -> None:
    s = (load_secrets() or {}).get("smtp")
    if not s or not to:
        return
    msg = EmailMessage()
    msg["From"] = s.get("from", s["user"])
    msg["To"] = to
    msg["Subject"] = "Your security-lab session is ready"
    msg.set_content(
        "Your reserved security-lab session is ready.\n\n"
        f"Open it here:\n{link}\n\n"
        + (f"Your booked time runs until {until}.\n\n" if until else "")
        + "Sign in once, then you can drive the live lab — open the streamed "
        "desktop into Cisco ISE, run device APIs, and reset it anytime.\n\n"
        "— labaccessnow.com\n"
    )
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(s["host"], int(s.get("port", 465)), context=ctx, timeout=20) as smtp:
        smtp.login(s["user"], s["password"])
        smtp.send_message(msg)
