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


# ------------------------------------------------------------------ 2: Phase 1 proof documents + income range
@migration(2, "phase1_proof_and_income")
def phase1_proof(c):
    # Income is stored as a band code (see income.py), not a number: people choose a range, and bands are what reports use.
    add_column(c, "alumni", "income_band", "TEXT")
    add_column(c, "alumni", "income_updated_at", "TEXT")
    add_column(c, "alumni", "verification_consent_at", "TEXT")      # when the person agreed to proof/income being collected
    c.executescript("""
    -- One row per upload. A newer upload replaces an older PENDING/REJECTED one (superseded_at); APPROVED proofs are kept
    -- as history. storage_key is a random name inside private storage and is never sent to any client.
    CREATE TABLE IF NOT EXISTS verification_documents(
      id INTEGER PRIMARY KEY,
      alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE,
      category TEXT NOT NULL,                 -- EMPLOYMENT | HIGHER_STUDIES | ENTREPRENEURSHIP
      doc_type TEXT NOT NULL,
      storage_key TEXT UNIQUE NOT NULL,
      original_name TEXT NOT NULL, content_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | APPROVED | REJECTED
      rejection_reason TEXT,
      uploaded_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT, superseded_at TEXT);
    CREATE INDEX IF NOT EXISTS idx_vdocs_alumni ON verification_documents(alumni_id);
    CREATE INDEX IF NOT EXISTS idx_vdocs_status ON verification_documents(status, superseded_at);
    """)


# ------------------------------------------------------------------ 3: Phase 1B profiles, career timeline, proof reminders
@migration(3, "phase1b_profiles_timeline_purpose")
def phase1b(c):
    # A campaign is either the usual "please update your details" reminder or a "please upload your proof" reminder.
    add_column(c, "campaigns", "purpose", "TEXT NOT NULL DEFAULT 'UPDATE'")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS profiles(
      alumni_id INTEGER PRIMARY KEY REFERENCES alumni(id) ON DELETE CASCADE,
      whatsapp TEXT, country TEXT, city TEXT, professional_domain TEXT, years_experience REAL, designation TEXT, headline TEXT,
      linkedin_url TEXT, github_url TEXT, portfolio_url TEXT, updated_at TEXT NOT NULL, updated_by TEXT);
    CREATE TABLE IF NOT EXISTS profile_skills(
      alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE, skill TEXT NOT NULL, PRIMARY KEY (alumni_id, skill));
    CREATE TABLE IF NOT EXISTS profile_interests(
      alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE, interest TEXT NOT NULL, PRIMARY KEY (alumni_id, interest));
    CREATE INDEX IF NOT EXISTS idx_profile_skills_skill ON profile_skills(skill);
    CREATE INDEX IF NOT EXISTS idx_profile_interests_interest ON profile_interests(interest);

    -- Append-only: only the three retracted_* columns can ever change, and only once. (Deleting a person still removes
    -- their events through the foreign key, which is the right thing for an erasure request.)
    CREATE TABLE IF NOT EXISTS career_events(
      id INTEGER PRIMARY KEY, alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE,
      event_type TEXT NOT NULL, event_date TEXT, title TEXT NOT NULL, organisation TEXT, detail TEXT,
      source TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT,
      retracted_at TEXT, retracted_by TEXT, retract_reason TEXT);
    CREATE INDEX IF NOT EXISTS idx_career_alumni ON career_events(alumni_id);
    CREATE TRIGGER IF NOT EXISTS career_events_immutable
      BEFORE UPDATE OF alumni_id, event_type, event_date, title, organisation, detail, source, created_at, created_by ON career_events
      BEGIN SELECT RAISE(ABORT, 'career_events are append-only: retract the event and add a new one'); END;
    CREATE TRIGGER IF NOT EXISTS career_events_retract_once
      BEFORE UPDATE OF retracted_at ON career_events WHEN OLD.retracted_at IS NOT NULL
      BEGIN SELECT RAISE(ABORT, 'this career event was already retracted'); END;
    """)
    # Backfill from what we already hold: graduation + the first job / studies / venture each person's records imply.
    # Done in Python (not SQL) so it uses exactly the same rules as new imports; safe to re-run, nothing is duplicated.
    from . import careers, profiles
    import json
    for r in c.execute("SELECT id FROM alumni").fetchall():
        careers.baseline(c, r["id"], source="MIGRATION")
    for r in c.execute("SELECT id, career_status, details FROM alumni WHERE details IS NOT NULL AND career_status IS NOT NULL").fetchall():
        try:
            details = json.loads(r["details"])
        except ValueError:
            continue
        careers.record_submission(c, r["id"], r["career_status"], details, source="MIGRATION")
        profiles.fill_from_submission(c, r["id"], r["career_status"], details)
