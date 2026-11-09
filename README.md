# AlumniConnect

Alumni data collection and reminder automation for a college department.
Faculty import the placement sheet, launch reminder campaigns, alumni open a personal link and submit their career details, and the system stops reminding anyone who has submitted.

Stack: React + Vite + Tailwind + lucide-react · FastAPI · SQLite · C++ processing engine (JSON over stdin/stdout) · SMTP + Telegram Bot API.

## Quick start

```bash
./run.sh            # builds engine, installs deps, starts API :8000 and UI :5173
```

Or manually:

```bash
make -C engine                                   # optional; falls back to Python if g++ is missing
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```

Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` (defaults `admin@vit.edu` / `ChangeMe@123`; **change them**, see `backend/.env.example`). That seeds the first **ADMIN** on an empty database only.
Tests: `cd backend && python -m pytest tests`.

## Data

There is **no seed or mock data**. On the first start with an empty database, the app loads `backend/data/reference_placement.xlsx` (Table 4.6.1 Placement Record, AY 2025-26) through the same validated importer used by the Import page. Set `AUTOLOAD_REFERENCE=0` to start empty.

That sheet has 56 rows but **51 unique PRNs**: five students (12210396, 12320028, 12320101, 12210538, 12210623) hold two offers each. The importer merges rows by PRN into one alumnus with several offers. Reports therefore show 51 students placed and 56 offers. The sheet's own Summary tab counts 56 as "students placed", which overstates the placement index.

The sheet contains real names, phone numbers and emails. Treat the repository, the database and any deployment as personal data under the DPDP Act: do not publish it, restrict access, and delete it when the purpose ends.

## Import validation (reference format)

`/dashboard/alumni/import` checks every upload against the reference sheet before anything is written:

- **Headers**: all 11 reference columns must be present (case, spacing and punctuation are ignored). The header row is found automatically in the first 25 rows. Extra columns are ignored with a note. A wrong file is rejected with a column-by-column checklist.
- **Rows**: name, PRN (8 digits), class, 10-digit mobile, email, employer and numeric package (LPA) are required. Position, letter reference/date and letter link are optional, as in the reference. Every problem is reported with its Excel row and column.
- **Cleaning** (reported as notes): `12320105-` becomes `12320105`; phone numbers stored as numbers or with `+91` are normalised; Excel serial dates and `21/08/2025`-style dates are converted; free text such as "hard copy attached" is kept as a note.
- **Graduation year** is read from the `AY: 2025-26` line (or entered manually for CSVs). The Summary tab's final-year student count is read if present.
- **Strict by default**: if any row is invalid the whole file is rejected. Tick *Skip invalid rows* to import only the valid ones. *Replace all existing data* wipes alumni, submissions and reminder history first; otherwise records merge by PRN.

`Download template` gives a blank file in the exact format.

## How it works

| Piece | Behaviour |
|---|---|
| Alumni link | `/update?token=…`, 192-bit random token, validated server-side on every call. **Expires after `TOKEN_TTL_DAYS` (30); each reminder renews it.** Staff can *Disable* or *Replace* a link from the alumni drawer (an expired/disabled link answers 410). Resubmitting through a live link updates the record (no duplicates). |
| Statuses | `PENDING` / `COMPLETED`; *overdue* = pending after the earliest started campaign's deadline. |
| Campaigns | Draft, running, paused, completed. Interval, max attempts, batch size and deadline are configurable. Templates accept `{{name}} {{batch}} {{unique_link}} {{prn}} {{employer}}`; unknown placeholders and a missing link are rejected. |
| Worker | Runs every `WORKER_TICK_SECONDS` and on *Run batch now*. Re-reads the alumnus' status immediately before each send, so a submission stops reminders at once. Skips completed and unsubscribed alumni. Failed sends retry on later ticks (3 tries, then the attempt is consumed); a rejected address or Telegram chat stops further attempts. |
| Delivery mode | Without `SMTP_HOST` / `TELEGRAM_BOT_TOKEN` the worker is **simulated**: it logs `SIMULATED` and contacts nobody. The Campaigns page says so. Telegram needs each alumnus' chat ID (set in the alumni drawer). |
| Search | One search box: an 8-digit PRN returns that single alumnus; anything else matches name, PRN, email or employer. |
| Undo | Delete and unsubscribe/re-subscribe can be undone from the Alumni page. |
| Export | Submissions and placement record, CSV or Excel. The placement export re-imports cleanly. |

### C++ engine (`engine/engine.cpp`)

Runs behind the API; nothing in the UI mentions it. It reads one JSON request on stdin and writes one JSON response: array + merge sort (export ordering), binary search (PRN lookup), doubly linked list (pending queue), binary-heap priority queue feeding a circular queue (reminder batches, ordered by days pending, missing position/letter and attempts so far), and a stack (undo). If the binary is not built, `backend/app/engine.py` uses an equivalent Python implementation (a test checks both give identical batches).

## Accounts, roles and security (Phase 0)

| Piece | Behaviour |
|---|---|
| Roles | `ADMIN` (everything), `FACULTY` (records, imports, exports, reminders, reports; no delete / users / audit), `ALUMNI` (own profile + privacy), `STUDENT` (directory only). Defined in `backend/app/rbac.py`; mirrored into the `roles`, `permissions`, `role_permissions` tables. Every API route names the permission it needs. |
| Sessions | Login creates a server-side session; the JWT is only valid while it is live. Logout, password change, disabling a user, or *End sessions* really end access. A user's role is read from the database on each request, so changes apply immediately. |
| Lockout | 5 wrong passwords lock the account for 15 min (same generic error either way, so accounts cannot be discovered). Per-IP and per-account rate limits on login. |
| Passwords | 10+ chars with a letter and a digit for any new password. Reset: emailed one-hour single-use link (only its hash is stored). Without SMTP the email is only simulated; use `python -m app.manage set-password --email …`. |
| Audit log | Append-only (database triggers reject edits/deletes). Records sign-ins (incl. failures), user/role changes, record views/edits/deletes, imports, exports, campaign actions, link actions, public submissions. Secrets are stripped. Admin page: *Audit log*. |
| Privacy | Per-alumnus level `PRIVATE` (default) / `ALUMNI_ONLY` / `INSTITUTION` / `PUBLIC`. Non-staff only ever receive name, batch, career type and organisation names: never contact details, PRN, salary or documents. A hidden profile answers 404. |
| Documents | `backend/app/storage.py`: validated (type + content signature + size), random keys, outside any served folder. HTTP endpoints arrive with Phase 1. |
| Migrations | Numbered, recorded in `schema_migrations` (`backend/app/migrations.py`). Phase 0 is migration 1 and upgrades an existing database in place. |
| Tunnel | Set `PUBLIC_URL`, `CORS_ORIGINS` and `TRUST_PROXY_HOPS=2` (tunnel → Vite → API) so rate limits see real visitors. |

**PostgreSQL later:** new tables use plain `INTEGER/TEXT/REAL` and Python-generated UTC timestamps. The SQLite-specific spots to port are `datetime('now')` and `INSERT OR IGNORE/REPLACE` in the original code, the `PRAGMA` column checks in `migrations.py`, and the audit-log triggers (use `REVOKE UPDATE, DELETE` or equivalent triggers).

## Known limits (MVP)

- Rate limiting is in-process (one API process). Move to Redis if you run several.
- Documents, consent on the public form and the alumni-facing directory arrive in later phases (see `plan.md`); do not expose real personal data publicly before Phase 1 is finished.
- SQLite and an in-process worker: run one API process. Move to PostgreSQL and a separate worker for more.
- Contact details come from the college email on the sheet (e.g. `@vit.edu` student addresses), which may stop working after graduation; collect personal emails in the form if reminders must keep reaching alumni.
- No unsubscribe link in outgoing messages yet; faculty toggle it per alumnus.
