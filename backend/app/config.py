import os
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent

load_dotenv(BASE / ".env", override=False)
AUTOLOAD_REFERENCE = os.getenv("AUTOLOAD_REFERENCE", "0") == "1"
DB_PATH = os.getenv("DB_PATH", str(BASE / "data" / "alumni.db"))
ENGINE_PATH = os.getenv("ENGINE_PATH", str(BASE.parent / "engine" / "build" / "engine"))
REFERENCE_XLSX = BASE / "data" / "reference_placement.xlsx"

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me-please-set-SECRET_KEY-in-env")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@vit.edu")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMe@123")
JWT_HOURS = int(os.getenv("JWT_HOURS", "12"))

PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5173")  # base for alumni links
CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o]

# Notifications. With no SMTP_HOST / TELEGRAM_BOT_TOKEN the worker runs in
# SIMULATED mode: it logs what it would send and never contacts anyone.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "alumni@vit.edu")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")  # optional; looked up with getMe if empty
TELEGRAM_POLL_SECONDS = int(os.getenv("TELEGRAM_POLL_SECONDS", "5"))  # how often to check for "Start" taps

WORKER_TICK_SECONDS = int(os.getenv("WORKER_TICK_SECONDS", "30"))
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "1") == "1"
