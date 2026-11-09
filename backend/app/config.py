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

# ---- Phase 0: security foundation -------------------------------------------------------------
APP_ENV = os.getenv("APP_ENV", "development").lower()           # "production" refuses unsafe defaults (see check_production)
DEV_SECRET_KEY = "dev-only-change-me-please-set-SECRET_KEY-in-env"
DEV_ADMIN_PASSWORD = "ChangeMe@123"
MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "10"))
LOCKOUT_THRESHOLD = int(os.getenv("LOCKOUT_THRESHOLD", "5"))     # consecutive wrong passwords before the account locks
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))
RESET_TOKEN_MINUTES = int(os.getenv("RESET_TOKEN_MINUTES", "60"))
# Public alumni links. Every link expires; sending a reminder renews it (rolling), and staff can revoke or replace it.
TOKEN_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "30"))
# Rate limiting is in-process (matches the single-process deployment). Behind a tunnel/reverse proxy every request
# would look like it comes from the proxy, so set TRUST_PROXY_HOPS to the number of proxies in front of the API
# (ngrok -> Vite -> API = 2). 0 = ignore X-Forwarded-For and use the socket address.
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") == "1"
TRUST_PROXY_HOPS = int(os.getenv("TRUST_PROXY_HOPS", "0"))
# Private document storage (verification documents arrive in Phase 1). Never served as static files.
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
STORAGE_ROOT = os.getenv("STORAGE_ROOT", str(BASE / "data" / "private_files"))
MAX_DOCUMENT_BYTES = int(os.getenv("MAX_DOCUMENT_BYTES", str(5 * 1024 * 1024)))


def check_production():
    """Refuse to start in production with the development defaults. Returns the list of problems (empty = fine)."""
    problems = []
    if SECRET_KEY == DEV_SECRET_KEY or len(SECRET_KEY) < 32:
        problems.append("SECRET_KEY must be set to a random string of at least 32 characters")
    if ADMIN_PASSWORD == DEV_ADMIN_PASSWORD:
        problems.append("ADMIN_PASSWORD is still the development default")
    if "*" in CORS_ORIGINS:
        problems.append("CORS_ORIGINS must list explicit origins, not '*'")
    return problems

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
