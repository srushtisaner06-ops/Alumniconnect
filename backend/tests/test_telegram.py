"""Telegram connect-link flow and the optional 'Telegram Chat ID' import column."""
import io

import openpyxl

from app import config, importer, notifier, services
from app.db import db


def _sheet(extra_header=None, extra_value=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    hdr = [h for _, h, _ in importer.COLUMNS] + ([extra_header] if extra_header else [])
    ws.append(["Table 4.6.1 Placement Record"])
    ws.append(hdr)
    ws.append(["AY: 2025-26 Placement"])
    row = [1, "Tele Test", 99000001, "BTech", "9876543210", "tele@example.com", "Acme", 6.5, "Dev", "", ""]
    ws.append(row + ([extra_value] if extra_header else []))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_import_reads_optional_chat_id():
    rep = importer.parse("t.xlsx", _sheet("Telegram Chat ID", 123456789))
    assert rep["ok"], rep["errors"]
    assert rep["students"][0]["telegram_chat_id"] == "123456789"


def test_import_without_column_still_ok():
    rep = importer.parse("t.xlsx", _sheet())
    assert rep["ok"] and rep["students"][0]["telegram_chat_id"] is None


def test_blank_chat_id_does_not_erase_existing(client, auth):
    rep = importer.parse("t.xlsx", _sheet("Telegram Chat ID", 555555555))
    with db() as c:
        services.import_students(c, rep["students"], rep["graduation_year"])
    rep2 = importer.parse("t.xlsx", _sheet())
    with db() as c:
        services.import_students(c, rep2["students"], rep2["graduation_year"])
        assert c.execute("SELECT telegram_chat_id t FROM alumni WHERE prn='99000001'").fetchone()["t"] == "555555555"


def test_connect_link_and_placeholder(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_USERNAME", "@MyBot")
    out = notifier.render("Tap {{telegram_link}}", {"name": "A", "graduation_year": 2026, "prn": "1", "token": "tok_123"})
    assert out == "Tap https://t.me/MyBot?start=tok_123"
    assert not notifier.unknown_placeholders("{{telegram_link}}")


def test_poll_links_chat_and_remembers_offset(monkeypatch):
    with db() as c:
        tok = c.execute("SELECT token FROM alumni WHERE prn='99000001'").fetchone()["token"]
        c.execute("UPDATE alumni SET telegram_chat_id=NULL WHERE prn='99000001'")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    seen, sent = [], []
    updates = [
        {"update_id": 10, "message": {"text": f"/start {tok}", "chat": {"id": 777, "type": "private"}}},
        {"update_id": 11, "message": {"text": "/start bogus", "chat": {"id": 888, "type": "private"}}},
        {"update_id": 12, "message": {"text": "hello", "chat": {"id": 999, "type": "private"}}},
    ]
    monkeypatch.setattr(notifier, "fetch_telegram_updates", lambda off: (seen.append(off), updates if off == 0 else [])[1])
    monkeypatch.setattr(notifier, "send_telegram", lambda chat, text: sent.append(chat))
    assert services.poll_telegram() == 1
    with db() as c:
        assert c.execute("SELECT telegram_chat_id t FROM alumni WHERE prn='99000001'").fetchone()["t"] == "777"
    assert services.poll_telegram() == 0 and seen == [0, 13]  # offset advanced past handled updates
    assert sent == ["777", "888"]
