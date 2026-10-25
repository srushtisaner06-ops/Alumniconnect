import re
import smtplib
from email.message import EmailMessage

import httpx

from . import config

PLACEHOLDERS = {"name", "batch", "unique_link", "prn", "employer"}
_PH = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def unknown_placeholders(*texts):
    return sorted({m for t in texts for m in _PH.findall(t or "")} - PLACEHOLDERS)


def render(template, alumnus):
    ctx = {"name": alumnus["name"], "batch": str(alumnus["graduation_year"]), "prn": alumnus["prn"],
           "unique_link": f"{config.PUBLIC_URL}/update?token={alumnus['token']}",
           "employer": alumnus.get("employer") or ""}
    return _PH.sub(lambda m: ctx.get(m.group(1), m.group(0)), template)


class PermanentError(Exception):
    """Contact is invalid; retrying will not help."""


def email_configured():
    return bool(config.SMTP_HOST)


def telegram_configured():
    return bool(config.TELEGRAM_BOT_TOKEN)


def send_email(to, subject, body):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    except smtplib.SMTPRecipientsRefused as e:
        raise PermanentError(f"recipient refused: {e}")


def send_telegram(chat_id, body):
    r = httpx.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                   json={"chat_id": chat_id, "text": body}, timeout=20)
    if r.status_code in (400, 403):
        raise PermanentError(f"telegram rejected chat id: {r.text[:120]}")
    r.raise_for_status()
