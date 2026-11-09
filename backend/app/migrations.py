"""Versioned schema migrations.

The original tables are created by `db.SCHEMA` (`CREATE TABLE IF NOT EXISTS`, unchanged so old databases keep working).
Everything added since lives here as numbered migrations that run once, in order, and are recorded in
`schema_migrations`. Rules for every future phase:

  * add a new `@migration(n, "name")` function; never edit an applied one;
  * make it idempotent (`has_column` / `IF NOT EXISTS`), because databases arrive in many historical shapes;
  * new tables use plain ANSI types (INTEGER / TEXT / REAL), timestamps are ISO-8601 UTC TEXT written by Python,
    and booleans are 0/1 INTEGER. That keeps the SQL portable to PostgreSQL (see the porting notes in README).
"""
from datetime import datetime, timedelta, timezone

from . import config

MIGRATIONS = []


def migration(version, name):
    def deco(fn):
        MIGRATIONS.append((version, name, fn))
        MIGRATIONS.sort(key=lambda m: m[0])
        return fn
    return deco


def has_column(c, table, column):
    return column in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def add_column(c, table, column, ddl):
    if not has_column(c, table, column):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def run(c):
    c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
    applied = []
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        fn(c)
        c.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                  (version, name, _ts(datetime.now(timezone.utc))))
        applied.append(version)
    return applied


# ------------------------------------------------------------------ 1: Phase 0 security foundation
@migration(1, "phase0_security_foundation")
def phase0(c):
    # ---- users: roles, lifecycle, lockout. Every user that exists *now* was an administrator (the only kind that
    # could exist), so they keep that role; any user created later must be given a role explicitly.
    fresh_role = not has_column(c, "users", "role")
    add_column(c, "users", "role", "TEXT NOT NULL DEFAULT 'STUDENT'")     # least privilege if a row ever forgets its role
    if fresh_role:
        c.execute("UPDATE users SET role='ADMIN'")
    add_column(c, "users", "full_name", "TEXT")
    add_column(c, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
    add_column(c, "users", "alumni_id", "INTEGER REFERENCES alumni(id) ON DELETE SET NULL")
    add_column(c, "users", "failed_logins", "INTEGER NOT NULL DEFAULT 0")
    add_column(c, "users", "locked_until", "TEXT")
    add_column(c, "users", "last_login_at", "TEXT")
    add_column(c, "users", "password_changed_at", "TEXT")
    add_column(c, "users", "created_at", "TEXT")
    c.execute("UPDATE users SET created_at=? WHERE created_at IS NULL", (_ts(datetime.now(timezone.utc)),))

    c.executescript("""
    CREATE TABLE IF NOT EXISTS roles(name TEXT PRIMARY KEY, description TEXT);
    CREATE TABLE IF NOT EXISTS permissions(name TEXT PRIMARY KEY, description TEXT);
    CREATE TABLE IF NOT EXISTS role_permissions(
      role TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE,
      permission TEXT NOT NULL REFERENCES permissions(name) ON DELETE CASCADE,
      PRIMARY KEY (role, permission));

    -- one account per alumni record
    CREATE UNIQUE INDEX IF NOT EXISTS ux_users_alumni ON users(alumni_id) WHERE alumni_id IS NOT NULL;

    -- Server-side sessions: a JWT is only honoured while its session row is live, so logout / disable / password
    -- change really end access (a bare JWT cannot be revoked).
    CREATE TABLE IF NOT EXISTS sessions(
      id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_seen_at TEXT, revoked_at TEXT,
      ip TEXT, user_agent TEXT);
    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

    -- Only the SHA-256 of a reset token is stored, so a database leak does not leak working reset links.
    CREATE TABLE IF NOT EXISTS password_resets(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT, requested_ip TEXT);

    -- Append-only: the triggers below make edits and deletes fail. No foreign keys, so history outlives the rows it describes.
    CREATE TABLE IF NOT EXISTS audit_logs(
      id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor_user_id INTEGER, actor_email TEXT, actor_role TEXT,
      action TEXT NOT NULL, entity_type TEXT, entity_id TEXT, outcome TEXT NOT NULL DEFAULT 'OK',
      ip TEXT, detail TEXT);
    CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(ts);
    CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
    CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_user_id);
    CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id);
    CREATE TRIGGER IF NOT EXISTS audit_logs_no_update BEFORE UPDATE ON audit_logs
      BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END;
    CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete BEFORE DELETE ON audit_logs
      BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END;

    -- Privacy by default: no row means PRIVATE. Levels: PRIVATE | ALUMNI_ONLY | INSTITUTION | PUBLIC.
    CREATE TABLE IF NOT EXISTS profile_visibility(
      alumni_id INTEGER PRIMARY KEY REFERENCES alumni(id) ON DELETE CASCADE,
      level TEXT NOT NULL DEFAULT 'PRIVATE', updated_at TEXT NOT NULL, updated_by TEXT);
    """)

    # ---- alumni: expiring, revocable personal links
    add_column(c, "alumni", "token_issued_at", "TEXT")
    add_column(c, "alumni", "token_expires_at", "TEXT")
    add_column(c, "alumni", "token_revoked_at", "TEXT")
    now = datetime.now(timezone.utc)
    # Links that already exist were issued with no expiry. Give each one a full lifetime from today (not an instant
    # cut-off) so links already sent keep working for a while; staff can regenerate any of them sooner.
    c.execute("UPDATE alumni SET token_issued_at=COALESCE(created_at, ?) WHERE token_issued_at IS NULL", (_ts(now),))
    c.execute("UPDATE alumni SET token_expires_at=? WHERE token_expires_at IS NULL",
              (_ts(now + timedelta(days=config.TOKEN_TTL_DAYS)),))
