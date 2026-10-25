import re
import smtplib
from email.message import EmailMessage

import httpx

from . import config

PLACEHOLDERS = {"name", "batch", "unique_link", "telegram_link", "prn", "employer"}
_PH = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def unknown_placeholders(*texts):
    return sorted({m for t in texts for m in _PH.findall(t or "")} - PLACEHOLDERS)


def render(template, alumnus):
    ctx = {"name": alumnus["name"], "batch": str(alumnus["graduation_year"]), "prn": alumnus["prn"],
           "unique_link": f"{config.PUBLIC_URL}/update?token={alumnus['token']}",
           "telegram_link": telegram_connect_link(alumnus["token"]),
           "employer": alumnus.get("employer") or ""}
    return _PH.sub(lambda m: ctx.get(m.group(1), m.group(0)), template)


class PermanentError(Exception):
    """Contact is invalid; retrying will not help."""


def email_configured():
    return bool(config.SMTP_HOST)


def telegram_configured():
    return bool(config.TELEGRAM_BOT_TOKEN)


_bot_username = None


def telegram_bot_username():
    """Bot username without '@'. From TELEGRAM_BOT_USERNAME, else asked from Telegram once (getMe)."""
    global _bot_username
    if config.TELEGRAM_BOT_USERNAME:
        return config.TELEGRAM_BOT_USERNAME.lstrip("@")
    if _bot_username is None and telegram_configured():
        try:
            r = httpx.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe", timeout=20)
            r.raise_for_status()
            _bot_username = r.json()["result"]["username"]
        except Exception as e:
            print("telegram getMe failed:", e)
    return _bot_username or ""


def telegram_connect_link(token):
    """t.me link that, when tapped and 'Start' is pressed, tells the bot which alumnus this chat belongs to."""
    u = telegram_bot_username()
    return f"https://t.me/{u}?start={token}" if u else "(Telegram bot not configured)"


def fetch_telegram_updates(offset):
    r = httpx.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates",
                  params={"offset": offset, "timeout": 0, "allowed_updates": '["message"]'}, timeout=20)
    r.raise_for_status()
    return r.json().get("result", [])


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
