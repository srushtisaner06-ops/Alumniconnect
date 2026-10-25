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

Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` (defaults `admin@vit.edu` / `ChangeMe@123`; **change them**, see `backend/.env.example`).
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
| Alumni link | `/update?token=…`, 192-bit random token, validated server-side on every call. Resubmitting through the same link updates the record (no duplicates). |
| Statuses | `PENDING` / `COMPLETED`; *overdue* = pending after the earliest started campaign's deadline. |
| Campaigns | Draft, running, paused, completed. Interval, max attempts, batch size and deadline are configurable. Templates accept `{{name}} {{batch}} {{unique_link}} {{prn}} {{employer}}`; unknown placeholders and a missing link are rejected. |
| Worker | Runs every `WORKER_TICK_SECONDS` and on *Run batch now*. Re-reads the alumnus' status immediately before each send, so a submission stops reminders at once. Skips completed and unsubscribed alumni. Failed sends retry on later ticks (3 tries, then the attempt is consumed); a rejected address or Telegram chat stops further attempts. |
| Delivery mode | Without `SMTP_HOST` / `TELEGRAM_BOT_TOKEN` the worker is **simulated**: it logs `SIMULATED` and contacts nobody. The Campaigns page says so. Telegram needs each alumnus' chat ID (set in the alumni drawer). |
| Search | One search box: an 8-digit PRN returns that single alumnus; anything else matches name, PRN, email or employer. |
| Undo | Delete and unsubscribe/re-subscribe can be undone from the Alumni page. |
| Export | Submissions and placement record, CSV or Excel. The placement export re-imports cleanly. |

### C++ engine (`engine/engine.cpp`)

Runs behind the API; nothing in the UI mentions it. It reads one JSON request on stdin and writes one JSON response: array + merge sort (export ordering), binary search (PRN lookup), doubly linked list (pending queue), binary-heap priority queue feeding a circular queue (reminder batches, ordered by days pending, missing position/letter and attempts so far), and a stack (undo). If the binary is not built, `backend/app/engine.py` uses an equivalent Python implementation (a test checks both give identical batches).

## Known limits (MVP)

- Alumni tokens do not expire and the public endpoints are not rate-limited; add both before exposing this publicly.
- SQLite and an in-process worker: run one API process. Move to PostgreSQL and a separate worker for more.
- Contact details come from the college email on the sheet (e.g. `@vit.edu` student addresses), which may stop working after graduation; collect personal emails in the form if reminders must keep reaching alumni.
- No unsubscribe link in outgoing messages yet; faculty toggle it per alumnus.
