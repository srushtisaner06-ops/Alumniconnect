import sqlite3
from contextlib import contextmanager
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alumni(
  id INTEGER PRIMARY KEY,
  sr_no INTEGER, name TEXT NOT NULL, prn TEXT UNIQUE NOT NULL, class_div TEXT,
  phone TEXT, email TEXT, telegram_chat_id TEXT,
  graduation_year INTEGER NOT NULL,
  token TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',          -- PENDING | COMPLETED
  unsubscribed INTEGER NOT NULL DEFAULT 0,
  career_status TEXT,                              -- EMPLOYMENT | HIGHER_STUDIES | ENTREPRENEURSHIP
  details TEXT,                                    -- JSON from the alumni form
  submitted_at TEXT,
  reminders_sent INTEGER NOT NULL DEFAULT 0,
  last_reminder_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS idx_alumni_status ON alumni(status);
CREATE TABLE IF NOT EXISTS offers(
  id INTEGER PRIMARY KEY, alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE,
  employer TEXT, package_lpa REAL, position TEXT, letter_ref TEXT, letter_link TEXT);
CREATE TABLE IF NOT EXISTS campaigns(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT',            -- DRAFT | RUNNING | PAUSED | COMPLETED
  channel TEXT NOT NULL DEFAULT 'email',           -- email | telegram | both
  interval_hours REAL NOT NULL DEFAULT 72,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  batch_size INTEGER NOT NULL DEFAULT 20,
  deadline TEXT,
  email_subject TEXT NOT NULL, email_body TEXT NOT NULL, telegram_body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), started_at TEXT);
CREATE TABLE IF NOT EXISTS reminder_log(
  id INTEGER PRIMARY KEY, campaign_id INTEGER, alumni_id INTEGER, channel TEXT,
  status TEXT,                                     -- SENT | SIMULATED | FAILED | SKIPPED
  attempt INTEGER, error TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS undo_actions(
  id INTEGER PRIMARY KEY, type TEXT NOT NULL, payload TEXT NOT NULL,
  label TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""


def connect():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


@contextmanager
def db():
    c = connect()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init():
    import os
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
