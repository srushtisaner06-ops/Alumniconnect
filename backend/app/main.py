import asyncio
import csv
import io
import json
import secrets
import os
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Optional

import openpyxl
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import accounts, audit, careers, config, documents, engine, importer, income, notifier, profiles, rbac, ratelimit, services, storage, visibility
from .db import db, init
from .security import Principal, current_principal, optional_principal, require

DEFAULT_EMAIL_SUBJECT = "Please update your career details – {{batch}} batch"
DEFAULT_EMAIL_BODY = ("Dear {{name}},\n\nThe department is collecting career information from the {{batch}} batch "
                      "for accreditation reports. It takes about two minutes.\n\nYour personal link:\n{{unique_link}}\n\n"
                      "Want reminders on Telegram instead? Open this link and press Start:\n{{telegram_link}}\n\n"
                      "Thank you,\nDepartment of Computer Science (AI)")
DEFAULT_TELEGRAM = "Hi {{name}}, please update your career details ({{batch}} batch): {{unique_link}}"


async def _worker():
    while True:
        await asyncio.sleep(config.WORKER_TICK_SECONDS)
        try:
            await asyncio.to_thread(services.run_all_running)
        except Exception as e:  # never let the worker die
            print("worker error:", e)


async def _telegram_poller():
    while True:
        await asyncio.sleep(config.TELEGRAM_POLL_SECONDS)
        try:
            await asyncio.to_thread(services.poll_telegram)
        except Exception as e:  # e.g. no network; keep trying
            print("telegram poll error:", e)


@asynccontextmanager
async def lifespan(app):
    if config.APP_ENV == "production":
        problems = config.check_production()
        if problems:
            raise RuntimeError("Refusing to start with APP_ENV=production: " + "; ".join(problems))
    elif config.SECRET_KEY == config.DEV_SECRET_KEY or config.ADMIN_PASSWORD == config.DEV_ADMIN_PASSWORD:
        print("WARNING: development SECRET_KEY / ADMIN_PASSWORD in use. Fine locally; set real values (and APP_ENV=production) before exposing this.")
    init()
    with db() as c:
        if not c.execute("SELECT 1 FROM users").fetchone():
            accounts.create_user(c, email=config.ADMIN_EMAIL, password=config.ADMIN_PASSWORD, role=rbac.ADMIN,
                                 full_name="Administrator", skip_password_policy=True)     # first-run seed only
        accounts.purge_old_sessions(c)
        try:
            documents.sweep_orphans(c)
        except Exception as e:                     # storage trouble must never stop the app from starting
            print("document sweep skipped:", e)
        # First run only: load the real placement sheet through the same validated importer.
        if os.getenv("AUTOLOAD_REFERENCE", "1") == "1" and not c.execute("SELECT 1 FROM alumni").fetchone() \
                and config.REFERENCE_XLSX.exists():
            rep = importer.parse(config.REFERENCE_XLSX.name, config.REFERENCE_XLSX.read_bytes())
            if rep["ok"]:
                services.import_students(c, rep["students"], rep["graduation_year"], final_year_students=rep["final_year_students"])
    tasks = [asyncio.create_task(_worker()), asyncio.create_task(_telegram_poller())] if config.WORKER_ENABLED else []
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="AlumniConnect", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _remember_client_ip(request: Request, call_next):
    """Make the client address available to audit.record() without threading `request` through every handler."""
    token = audit.client_ip_var.set(ratelimit.client_ip(request))
    try:
        return await call_next(request)
    finally:
        audit.client_ip_var.reset(token)


@app.exception_handler(accounts.AccountError)
async def _account_error(request: Request, exc: accounts.AccountError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.exception_handler(careers.CareerError)
async def _career_error(request: Request, exc: careers.CareerError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.exception_handler(profiles.ProfileError)
async def _profile_error(request: Request, exc: profiles.ProfileError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


# ================================================================ auth
class Login(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


def _session_payload(user, token=None, expires=None):
    out = {"email": user["email"], "role": user["role"], "full_name": user["full_name"],
           "permissions": sorted(rbac.permissions_for(user["role"]))}
    if token:
        out.update(token=token, expires_at=expires.strftime("%Y-%m-%d %H:%M:%S"))
    return out


@app.post("/api/auth/login")
def login(body: Login, request: Request):
    ip = ratelimit.client_ip(request)
    email = accounts.normalize_email(body.email)
    ratelimit.check("login_ip", ip)
    ratelimit.check("login", f"{ip}|{email}")
    with db() as c:
        user, reason = accounts.authenticate(c, email, body.password)
        if user:
            token, exp, sid = accounts.start_session(c, user, ip, request.headers.get("user-agent"))
            audit.record(c, "auth.login", Principal(user["id"], user["email"], user["role"], sid), entity_type="user", entity_id=user["id"])
        else:   # recorded and committed here; the error is raised after the block so the audit row and the failure counter persist
            audit.record(c, "auth.login", None, actor_email=email, outcome="FAILED", detail={"reason": reason})
    if not user:
        raise HTTPException(401, accounts.GENERIC_LOGIN_ERROR)
    return _session_payload(user, token, exp)


@app.get("/api/auth/me")
def me(who: Principal = Depends(current_principal)):
    return {"id": who.user_id, "email": who.email, "role": who.role, "full_name": who.full_name, "alumni_id": who.alumni_id,
            "permissions": sorted(who.permissions)}


@app.post("/api/auth/logout")
def logout(who: Principal = Depends(current_principal)):
    with db() as c:
        accounts.revoke_session(c, who.user_id, who.session_id)
        audit.record(c, "auth.logout", who, entity_type="user", entity_id=who.user_id)
    return {"ok": True}


@app.post("/api/auth/logout-all")
def logout_all(who: Principal = Depends(current_principal)):
    with db() as c:
        n = accounts.revoke_user_sessions(c, who.user_id)
        audit.record(c, "auth.logout_all", who, entity_type="user", entity_id=who.user_id, detail={"sessions": n})
    return {"ok": True, "sessions_ended": n}


@app.get("/api/auth/sessions")
def my_sessions(who: Principal = Depends(current_principal)):
    with db() as c:
        return {"items": accounts.list_sessions(c, who.user_id, who.session_id)}


@app.delete("/api/auth/sessions/{sid}")
def end_session(sid: str, who: Principal = Depends(current_principal)):
    with db() as c:
        if not accounts.revoke_session(c, who.user_id, sid):
            raise HTTPException(404, "Session not found")
        audit.record(c, "auth.session_end", who, entity_type="session", entity_id=sid[:8])
    return {"ok": True}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


@app.post("/api/auth/change-password")
def change_password(body: PasswordChange, who: Principal = Depends(current_principal)):
    with db() as c:
        ended = accounts.change_password(c, who.user_id, who.email, body.current_password, body.new_password, keep_sid=who.session_id)
        audit.record(c, "auth.password_change", who, entity_type="user", entity_id=who.user_id, detail={"other_sessions_ended": ended})
    return {"ok": True, "other_sessions_ended": ended}


class ResetRequest(BaseModel):
    email: str = Field(max_length=200)


def _send_reset_email(email, raw_token):
    body = ("A password reset was requested for your AlumniConnect account.\n\n"
            f"Open this link within {config.RESET_TOKEN_MINUTES} minutes to choose a new password:\n"
            f"{config.PUBLIC_URL}/reset-password?token={raw_token}\n\n"
            "If you did not ask for this, ignore this message; your password has not changed.")
    if notifier.email_configured():
        try:
            notifier.send_email(email, "Reset your AlumniConnect password", body)
        except Exception as e:
            print("password-reset email failed:", e)
    else:
        print(f"SIMULATED password-reset email to {email} (SMTP is not configured; use `python -m app.manage set-password`)")


@app.post("/api/auth/password-reset/request", dependencies=[Depends(ratelimit.by_ip("reset_request"))])
def password_reset_request(body: ResetRequest, background: BackgroundTasks):
    email = accounts.normalize_email(body.email)
    with db() as c:
        res = accounts.create_password_reset(c, email)
        audit.record(c, "auth.password_reset_request", None, actor_email=email, detail={"account_found": bool(res)})
    if res:   # sent after the response, so the reply takes the same time whether or not the account exists
        background.add_task(_send_reset_email, res[0]["email"], res[1])
    return {"ok": True, "message": "If that email belongs to an account, a reset link has been sent."}


class ResetConfirm(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


@app.post("/api/auth/password-reset/confirm", dependencies=[Depends(ratelimit.by_ip("reset_confirm"))])
def password_reset_confirm(body: ResetConfirm):
    with db() as c:
        user, reason = accounts.consume_password_reset(c, body.token, body.new_password)
        audit.record(c, "auth.password_reset", None, actor_email=user["email"] if user else None,
                     outcome="OK" if user else "FAILED", entity_type="user", entity_id=user["id"] if user else None)
    if not user:
        raise HTTPException(400, "This reset link is invalid or has expired. Request a new one.")
    return {"ok": True}


# ---------------------------------------------------------------- user management (ADMIN)
class UserIn(BaseModel):
    email: str = Field(max_length=200)
    password: Optional[str] = Field(None, max_length=200)     # omit it to send an invite: the person chooses their own password
    role: str
    full_name: Optional[str] = Field(None, max_length=120)
    alumni_id: Optional[int] = None


class UserPatch(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = Field(None, max_length=120)


@app.get("/api/roles")
def roles(who: Principal = Depends(require("user.manage"))):
    return {"roles": [{"name": r, "description": d, "permissions": sorted(rbac.permissions_for(r))} for r, d in rbac.ROLES.items()],
            "permissions": rbac.PERMISSIONS}


@app.get("/api/users")
def users(who: Principal = Depends(require("user.manage"))):
    with db() as c:
        return {"items": accounts.list_users(c)}


def _send_invite_email(email, raw_token):
    body = ("An AlumniConnect account has been created for you.\n\n"
            f"Open this link within {config.INVITE_HOURS} hours to choose your password:\n"
            f"{config.PUBLIC_URL}/reset-password?token={raw_token}\n\n"
            "If you were not expecting this, you can ignore this message.")
    try:
        notifier.send_email(email, "Your AlumniConnect account", body)
    except Exception as e:
        print("invite email failed:", e)


@app.post("/api/users")
def create_user(body: UserIn, background: BackgroundTasks, who: Principal = Depends(require("user.manage"))):
    """With a password: the account is ready to use. Without one: an invite. The person gets a link to choose their own
    password, so an administrator never has to know or send one. If email is not set up the link is returned here, once,
    for the administrator to pass on."""
    invite = body.password is None
    with db() as c:
        uid = accounts.create_user(c, email=body.email, password=body.password or secrets.token_urlsafe(24), role=body.role,
                                   full_name=body.full_name, alumni_id=body.alumni_id, skip_password_policy=invite)
        link = None
        if invite:
            _, raw = accounts.create_password_reset(c, body.email, minutes=config.INVITE_HOURS * 60)
            link = f"{config.PUBLIC_URL}/reset-password?token={raw}"
        audit.record(c, "user.create", who, entity_type="user", entity_id=uid,
                     detail={"email": accounts.normalize_email(body.email), "role": body.role, "alumni_id": body.alumni_id, "invited": invite})
    out = {"id": uid, "invited": invite}
    if invite:
        if notifier.email_configured():
            background.add_task(_send_invite_email, accounts.normalize_email(body.email), link.split("token=")[1])
            out["emailed"] = True
        else:
            out.update(emailed=False, invite_link=link)
    return out


@app.patch("/api/users/{uid}")
def patch_user(uid: int, body: UserPatch, who: Principal = Depends(require("user.manage"))):
    with db() as c:
        change = accounts.update_user(c, who, uid, role=body.role, is_active=body.is_active, full_name=body.full_name)
        audit.record(c, "user.update", who, entity_type="user", entity_id=uid, detail=change)
    return {"ok": True}


@app.post("/api/users/{uid}/revoke-sessions")
def revoke_sessions(uid: int, who: Principal = Depends(require("user.manage"))):
    with db() as c:
        if not c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            raise HTTPException(404, "User not found")
        n = accounts.revoke_user_sessions(c, uid)
        audit.record(c, "user.sessions_revoked", who, entity_type="user", entity_id=uid, detail={"sessions": n})
    return {"ok": True, "sessions_ended": n}


@app.get("/api/audit-logs")
def audit_logs(action: str = "", actor: str = "", entity_type: str = "", entity_id: str = "", outcome: str = "",
               since: str = "", until: str = "", page: int = 1, page_size: int = Query(50, le=200),
               who: Principal = Depends(require("audit.view"))):
    with db() as c:
        return audit.search(c, action=action.strip(), actor=actor.strip(), entity_type=entity_type.strip(),
                            entity_id=entity_id.strip(), outcome=outcome.strip(), since=since.strip(), until=until.strip(),
                            page=page, page_size=page_size)


# ================================================================ dashboard / analytics
@app.get("/api/dashboard")
def dashboard(who: Principal = Depends(require("report.view"))):
    with db() as c:
        data = services.analytics(c)
        recs = [dict(r) for r in c.execute("SELECT id,prn,status FROM alumni")]
        ids = engine.pending_list(recs)[:8]
        nxt = []
        for i in ids:
            r = c.execute("SELECT id,name,prn,email FROM alumni WHERE id=?", (i,)).fetchone()
            nxt.append(dict(r))
        data["next_pending"] = nxt
        data["campaigns"] = [dict(r) for r in c.execute("SELECT id,name,status FROM campaigns ORDER BY id DESC LIMIT 3")]
    return data


@app.get("/api/reports/analytics")
def reports(who: Principal = Depends(require("report.view"))):
    with db() as c:
        return services.analytics(c)


EXPORT_SCOPES = {"submissions": None, "placement": importer.PLACEMENT,
                 "higher_studies": importer.HIGHER_STUDIES, "entrepreneurship": importer.ENTREPRENEURSHIP}


@app.get("/api/reports/export")
def export(scope: str = "submissions", format: str = "xlsx", who: Principal = Depends(require("export.run"))):
    if scope not in EXPORT_SCOPES or format not in ("csv", "xlsx"):
        raise HTTPException(422, "scope must be submissions|placement|higher_studies|entrepreneurship, format csv|xlsx")
    category = EXPORT_SCOPES[scope]
    with db() as c:
        meta = [dict(r) for r in c.execute("SELECT id,prn,graduation_year,status FROM alumni")]
        order = engine.sort_ids(meta, "graduation_year")
        rows = []
        for aid in order:
            a = services.alumnus_dict(c, c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone())
            base = [a["sr_no"], a["name"], a["prn"], a["class_div"], a["phone"], a["email"]]
            if category == importer.PLACEMENT:
                for o in a["offers"]:
                    rows.append(base + [o["employer"], o["package_lpa"], o["position"], o["letter_ref"], o["letter_link"]])
            elif category == importer.HIGHER_STUDIES:
                for h in a["higher_studies"]:
                    rows.append(base + [h["degree"], h["institution"], h["letter_link"]])
            elif category == importer.ENTREPRENEURSHIP:
                for v in a["ventures"]:
                    rows.append(base + [v["company"], v["registration_no"], v["website"], v["letter_link"]])
            else:
                d = a["details"] or {}
                rows.append([a["name"], a["prn"], a["graduation_year"], a["email"], a["phone"], a["status"],
                             a["career_status"] or "", a["submitted_at"] or "", a["reminders_sent"],
                             d.get("company") or d.get("university") or d.get("startup_name") or "",
                             d.get("designation") or d.get("degree") or d.get("business_domain") or "",
                             d.get("industry") or d.get("country") or d.get("stage") or "",
                             d.get("specialization") or d.get("notes") or "",
                             a["income_label"] or "", (a["proof"] or {}).get("status", "MISSING")])
    if category:
        head = importer.headers(category)      # same headers as the reference sheet, so the export re-imports as-is
    else:
        head = ["Name", "PRN", "Graduation Year", "Email", "Phone", "Status", "Career Status", "Submitted At", "Reminders Sent",
                "Company / University / Startup", "Designation / Degree / Domain", "Industry / Country / Stage", "Specialization / Notes", "Income Range", "Proof Status"]
    fname = f"alumni_{scope}"
    with db() as c:
        audit.record(c, "export.run", who, entity_type="export", entity_id=scope, detail={"format": format, "rows": len(rows)})
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows(rows)
        return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(head)
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})


# ================================================================ alumni
@app.get("/api/alumni")
def list_alumni(search: str = "", status: str = "all", category: str = "all", page: int = 1, page_size: int = Query(25, le=100), who: Principal = Depends(require("alumni.read"))):
    q = search.strip()
    where, args = [], []
    if category != "all" and category not in services.CATEGORY_TABLES:
        raise HTTPException(422, "category must be all|PLACEMENT|HIGHER_STUDIES|ENTREPRENEURSHIP")
    with db() as c:
        if importer.PRN_RE.fullmatch(q):         # PRN lookup
            recs = [dict(r) for r in c.execute("SELECT id,prn FROM alumni")]
            hit = engine.search_prn(recs, q)
            where.append("a.id=?")
            args.append(hit if hit is not None else -1)
        elif q:
            like = f"%{q}%"
            where.append("(a.name LIKE ? OR a.prn LIKE ? OR a.email LIKE ? OR a.id IN (SELECT alumni_id FROM offers WHERE employer LIKE ?)"
                         " OR a.id IN (SELECT alumni_id FROM higher_studies WHERE institution LIKE ? OR degree LIKE ?)"
                         " OR a.id IN (SELECT alumni_id FROM ventures WHERE company LIKE ?))")
            args += [like] * 7
        if category != "all":
            where.append(f"EXISTS (SELECT 1 FROM {services.CATEGORY_TABLES[category]} t WHERE t.alumni_id=a.id)")
        cutoff = services.overdue_cutoff(c)
        today = services.now().strftime("%Y-%m-%d")
        is_overdue = bool(cutoff and cutoff < today)
        if status == "COMPLETED":
            where.append("a.status='COMPLETED'")
        elif status == "OVERDUE":
            where.append("a.status='PENDING'" if is_overdue else "0")
        elif status == "PENDING":
            where.append("a.status='PENDING'" + (" AND 0" if is_overdue else ""))
        w = ("WHERE " + " AND ".join(where)) if where else ""
        total = c.execute(f"SELECT COUNT(*) n FROM alumni a {w}", args).fetchone()["n"]
        rows = c.execute(f"SELECT a.* FROM alumni a {w} ORDER BY a.sr_no, a.id LIMIT ? OFFSET ?",
                         args + [page_size, (max(page, 1) - 1) * page_size]).fetchall()
        items = []
        for r in rows:
            d = services.alumnus_dict(c, r)
            d.pop("token")
            items.append(d)
        counts = {"all": c.execute("SELECT COUNT(*) n FROM alumni").fetchone()["n"]}
        for cat, table in services.CATEGORY_TABLES.items():
            counts[cat] = c.execute(f"SELECT COUNT(DISTINCT alumni_id) n FROM {table}").fetchone()["n"]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "category_counts": counts}


@app.get("/api/alumni/{aid}")
def get_alumnus(aid: int, who: Principal = Depends(require("alumni.read"))):
    with db() as c:
        r = c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()
        if not r:
            raise HTTPException(404, "Not found")
        d = services.alumnus_dict(c, r)
        d["link"] = f"{config.PUBLIC_URL}/update?token={d.pop('token')}"
        if who.has("verification.review"):
            d["documents"] = documents.history(c, aid)
        d["profile"] = profiles.get(c, aid)
        d["career_events"] = careers.list_events(c, aid)
        if who.has("user.manage"):
            u = c.execute("SELECT id,email,is_active,role FROM users WHERE alumni_id=?", (aid,)).fetchone()
            d["account"] = {**dict(u), "is_active": bool(u["is_active"])} if u else None
        audit.record(c, "alumni.view", who, entity_type="alumni", entity_id=aid)
        d["history"] = [dict(x) for x in c.execute(
            "SELECT l.*, cm.name campaign FROM reminder_log l LEFT JOIN campaigns cm ON cm.id=l.campaign_id WHERE alumni_id=? ORDER BY l.id DESC LIMIT 20", (aid,))]
    return d


class AlumniPatch(BaseModel):
    telegram_chat_id: Optional[str] = Field(None, max_length=40)
    unsubscribed: Optional[bool] = None


@app.patch("/api/alumni/{aid}")
def patch_alumnus(aid: int, body: AlumniPatch, who: Principal = Depends(require("alumni.write"))):
    with db() as c:
        r = c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()
        if not r:
            raise HTTPException(404, "Not found")
        if body.telegram_chat_id is not None:
            c.execute("UPDATE alumni SET telegram_chat_id=? WHERE id=?", (body.telegram_chat_id.strip() or None, aid))
            audit.record(c, "alumni.update", who, entity_type="alumni", entity_id=aid, detail={"field": "telegram_chat_id"})
        if body.unsubscribed is not None and int(body.unsubscribed) != r["unsubscribed"]:
            services.push_undo(c, "set_unsubscribed", {"id": aid, "previous": r["unsubscribed"]},
                               f"{'Unsubscribed' if body.unsubscribed else 'Re-subscribed'} {r['name']}")
            c.execute("UPDATE alumni SET unsubscribed=? WHERE id=?", (int(body.unsubscribed), aid))
            audit.record(c, "alumni.update", who, entity_type="alumni", entity_id=aid, detail={"unsubscribed": bool(body.unsubscribed)})
    return {"ok": True}


@app.delete("/api/alumni/{aid}")
def delete_alumnus(aid: int, who: Principal = Depends(require("alumni.delete"))):
    with db() as c:
        r = c.execute("SELECT name FROM alumni WHERE id=?", (aid,)).fetchone()
        if not r:
            raise HTTPException(404, "Not found")
        services.push_undo(c, "delete_alumni", services.snapshot(c, aid), f"Deleted {r['name']}")
        keys = documents.purge_alumni(c, aid)
        c.execute("DELETE FROM alumni WHERE id=?", (aid,))
        audit.record(c, "alumni.delete", who, entity_type="alumni", entity_id=aid, detail={"name": r["name"], "documents_removed": len(keys)})
    documents.remove_files(keys)                   # after the commit, so a rollback never loses a file
    return {"ok": True}


@app.get("/api/undo")
def undo_peek(who: Principal = Depends(require("alumni.write"))):
    with db() as c:
        rows = c.execute("SELECT id,label FROM undo_actions ORDER BY id").fetchall()
        return {"count": len(rows), "next": rows[-1]["label"] if rows else None}


@app.post("/api/undo")
def undo(who: Principal = Depends(require("alumni.write"))):
    with db() as c:
        label = services.undo_last(c)
        if label is not None:
            audit.record(c, "alumni.undo", who, detail={"undone": label})
    if label is None:
        raise HTTPException(404, "Nothing to undo")
    return {"undone": label}


# ================================================================ import
@app.get("/api/import/formats")
def import_formats(who: Principal = Depends(require("import.run"))):
    """The three record types and their exact column headers (shown on the Import page)."""
    return {"formats": importer.formats()}


@app.get("/api/import/template")
def import_template(category: str = importer.PLACEMENT, who: Principal = Depends(require("import.run"))):
    if category not in importer.CATEGORIES:
        raise HTTPException(422, "category must be PLACEMENT|HIGHER_STUDIES|ENTREPRENEURSHIP")
    fname = {importer.PLACEMENT: "placement", importer.HIGHER_STUDIES: "higher_studies",
             importer.ENTREPRENEURSHIP: "entrepreneurship"}[category]
    return Response(importer.template_workbook(category),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}_template.xlsx"'})


MAX_UPLOAD = 5 * 1024 * 1024


async def _read_upload(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 5 MB)")
    return data


def _public_report(rep):
    return {k: v for k, v in rep.items() if k != "students"}


@app.post("/api/import/validate")
async def import_validate(file: UploadFile = File(...), graduation_year: Optional[int] = Form(None),
                          category: Optional[str] = Form(None), who: Principal = Depends(require("import.run"))):
    rep = importer.parse(file.filename, await _read_upload(file), graduation_year, category or None)
    with db() as c:
        existing = {r["prn"] for r in c.execute("SELECT prn FROM alumni")}
    rep["already_in_database"] = sum(1 for s in rep["students"] if s["prn"] in existing)
    return _public_report(rep)


@app.post("/api/import")
async def import_commit(file: UploadFile = File(...), graduation_year: Optional[int] = Form(None),
                        category: Optional[str] = Form(None),
                        replace: bool = Form(False), skip_invalid: bool = Form(False), who: Principal = Depends(require("import.run"))):
    rep = importer.parse(file.filename, await _read_upload(file), graduation_year, category or None)
    fatal = rep["missing_columns"] or not rep["graduation_year"] or not rep["students"] or rep["header_row"] is None \
        or not rep["category"]
    if fatal or (rep["errors"] and not skip_invalid):
        raise HTTPException(422, {"message": "File does not match the reference format", "report": _public_report(rep)})
    with db() as c:
        doc_keys = []
        if replace:
            c.execute("DELETE FROM import_batches")   # their alumni are wiped below, so the file history goes too
            doc_keys = documents.purge_all(c)
        imp = c.execute("INSERT INTO import_batches(filename,graduation_year,category) VALUES(?,?,?)",
                        ((file.filename or "upload")[:200], rep["graduation_year"], rep["category"])).lastrowid
        res = services.import_students(c, rep["students"], rep["graduation_year"], replace=replace,
                                       final_year_students=rep["final_year_students"], import_id=imp)
        c.execute("UPDATE import_batches SET added=?, updated=?, unique_students=? WHERE id=?",
                  (res["added"], res["updated"], len(rep["students"]), imp))
        audit.record(c, "import.commit", who, entity_type="import", entity_id=imp,
                     detail={"filename": (file.filename or "upload")[:200], "category": rep["category"], "replace_all": replace,
                             "skip_invalid": skip_invalid, "added": res["added"], "updated": res["updated"]})
    documents.remove_files(doc_keys)
    res["import_id"] = imp
    res["skipped_rows"] = len({e["row"] for e in rep["errors"] if e["row"]})
    return {"ok": True, **res, "unique_students": len(rep["students"]), "replaced": replace,
            "category": rep["category"], "category_label": rep["category_label"]}


# ================================================================ campaigns
class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel: str = "email"
    interval_hours: float = Field(72, ge=0.01, le=24 * 60)
    max_attempts: int = Field(3, ge=1, le=20)
    batch_size: int = Field(20, ge=1, le=500)
    deadline: Optional[str] = None
    email_subject: str = DEFAULT_EMAIL_SUBJECT
    email_body: str = DEFAULT_EMAIL_BODY
    telegram_body: str = DEFAULT_TELEGRAM
    purpose: str = "UPDATE"      # UPDATE = remind people who have not submitted; PROOF = remind people who have no proof on file
    # {"all": bool, "batches": [years], "import_ids": [ids], "alumni_ids": [ids]}.
    # Omitted (null) = leave unchanged on update / everyone on create (the behaviour before this feature).
    recipients: Optional[dict] = None


def _validate_campaign(b: CampaignIn):
    if b.channel not in ("email", "telegram", "both"):
        raise HTTPException(422, "channel must be email, telegram or both")
    if b.purpose not in ("UPDATE", "PROOF"):
        raise HTTPException(422, "purpose must be UPDATE or PROOF")
    bad = notifier.unknown_placeholders(b.email_subject, b.email_body, b.telegram_body)
    if bad:
        raise HTTPException(422, f"Unknown placeholder(s): {', '.join('{{' + x + '}}' for x in bad)}. "
                                 f"Allowed: {', '.join('{{' + x + '}}' for x in sorted(notifier.PLACEHOLDERS))}")
    used = ([b.email_body] if b.channel in ("email", "both") else []) + ([b.telegram_body] if b.channel in ("telegram", "both") else [])
    if any("{{unique_link}}" not in re.sub(r"\s", "", t) for t in used):
        raise HTTPException(422, "Every message template in use must include {{unique_link}} so alumni can open their form")
    if b.deadline and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", b.deadline):
        raise HTTPException(422, "deadline must be YYYY-MM-DD")
    if b.recipients is not None and services.selection_is_empty(services.normalize_selection(b.recipients)):
        raise HTTPException(422, "Choose who to remind: everyone, a batch, an imported file or specific people")


def _campaign_stats(c, row):
    d = dict(row)
    d["sent"] = c.execute("SELECT COUNT(*) n FROM reminder_log WHERE campaign_id=? AND status IN ('SENT','SIMULATED')", (row["id"],)).fetchone()["n"]
    d["failed"] = c.execute("SELECT COUNT(*) n FROM reminder_log WHERE campaign_id=? AND status='FAILED'", (row["id"],)).fetchone()["n"]
    d["eligible_now"] = len(services.eligible(c, row))
    d["reachable"] = services.eligible_total(c, row)
    sel = services.get_selection(c, row["id"])
    if sel is None:   # created before recipient selection existed: contacts everyone
        d["recipients"] = {"all": True, "batches": [], "import_ids": [], "alumni_ids": [], "people": [], "legacy": True}
        d["recipient_total"] = c.execute("SELECT COUNT(*) n FROM alumni").fetchone()["n"]
    else:
        d["recipients"] = {**sel, "people": services.people_for(c, sel["alumni_ids"])}
        d["recipient_total"] = len(services.resolve_selection(c, sel))
    return d


@app.get("/api/campaigns")
def list_campaigns(who: Principal = Depends(require("campaign.manage"))):
    with db() as c:
        rows = c.execute("SELECT * FROM campaigns ORDER BY id DESC").fetchall()
        return {"items": [_campaign_stats(c, r) for r in rows],
                "mode": {"email": "live" if notifier.email_configured() else "simulated",
                         "telegram": "live" if notifier.telegram_configured() else "simulated"},
                "placeholders": sorted(notifier.PLACEHOLDERS)}


@app.post("/api/campaigns")
def create_campaign(b: CampaignIn, who: Principal = Depends(require("campaign.manage"))):
    _validate_campaign(b)
    deadline = b.deadline or (services.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    with db() as c:
        cid = c.execute("""INSERT INTO campaigns(name,channel,interval_hours,max_attempts,batch_size,deadline,email_subject,email_body,telegram_body,purpose)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""", (b.name, b.channel, b.interval_hours, b.max_attempts, b.batch_size, deadline,
                                                            b.email_subject, b.email_body, b.telegram_body, b.purpose)).lastrowid
        if b.recipients is not None:
            services.save_selection(c, cid, services.normalize_selection(b.recipients))
        audit.record(c, "campaign.create", who, entity_type="campaign", entity_id=cid, detail={"name": b.name, "channel": b.channel, "purpose": b.purpose})
    return {"id": cid}


@app.put("/api/campaigns/{cid}")
def update_campaign(cid: int, b: CampaignIn, who: Principal = Depends(require("campaign.manage"))):
    _validate_campaign(b)
    with db() as c:
        existing = c.execute("SELECT purpose FROM campaigns WHERE id=?", (cid,)).fetchone()
        if not existing:
            raise HTTPException(404, "Not found")
        if existing["purpose"] != b.purpose:       # who is being reminded of what would silently change under a running campaign
            raise HTTPException(409, "A campaign's purpose cannot be changed. Create a new campaign instead.")
        c.execute("""UPDATE campaigns SET name=?,channel=?,interval_hours=?,max_attempts=?,batch_size=?,deadline=?,
                     email_subject=?,email_body=?,telegram_body=? WHERE id=?""",
                  (b.name, b.channel, b.interval_hours, b.max_attempts, b.batch_size, b.deadline, b.email_subject,
                   b.email_body, b.telegram_body, cid))
        if b.recipients is not None:
            services.save_selection(c, cid, services.normalize_selection(b.recipients))
        audit.record(c, "campaign.update", who, entity_type="campaign", entity_id=cid, detail={"name": b.name})
    return {"ok": True}


# ---- recipient selection helpers (used by the campaign editor)
@app.get("/api/recipients/options")
def recipient_options(who: Principal = Depends(require("campaign.manage"))):
    with db() as c:
        return services.recipient_options(c)


@app.get("/api/recipients/search")
def recipient_search(q: str = "", who: Principal = Depends(require("campaign.manage"))):
    q = q.strip()
    if len(q) < 2:
        return {"items": []}
    like = f"%{q}%"
    with db() as c:
        rows = c.execute("SELECT id,name,prn,email,graduation_year,status FROM alumni "
                         "WHERE name LIKE ? OR prn LIKE ? OR email LIKE ? ORDER BY name LIMIT 15", (like, like, like)).fetchall()
    return {"items": [dict(r) for r in rows]}


class PreviewIn(BaseModel):
    recipients: dict
    channel: str = "email"
    max_attempts: int = Field(3, ge=1, le=20)
    purpose: str = "UPDATE"


@app.post("/api/recipients/preview")
def recipient_preview(b: PreviewIn, who: Principal = Depends(require("campaign.manage"))):
    if b.channel not in ("email", "telegram", "both"):
        raise HTTPException(422, "channel must be email, telegram or both")
    with db() as c:
        return services.preview_recipients(c, services.normalize_selection(b.recipients), b.channel, b.max_attempts,
                                           b.purpose if b.purpose in ("UPDATE", "PROOF") else "UPDATE")


@app.post("/api/campaigns/{cid}/{action}")
def campaign_action(cid: int, action: str, who: Principal = Depends(require("campaign.manage"))):
    with db() as c:
        row = c.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        st = row["status"]
        if action in ("start", "resume"):
            if st not in ("DRAFT", "PAUSED", "COMPLETED"):
                raise HTTPException(409, f"This round is already {st}")
            c.execute("UPDATE campaigns SET status='RUNNING', started_at=COALESCE(started_at, datetime('now')) WHERE id=?", (cid,))
        elif action == "pause":
            if st != "RUNNING":
                raise HTTPException(409, "Only a running round can be paused")
            c.execute("UPDATE campaigns SET status='PAUSED' WHERE id=?", (cid,))
        elif action == "run-now":
            if st != "RUNNING":
                raise HTTPException(409, "Start the round first")
        else:
            raise HTTPException(404, "Unknown action")
        audit.record(c, f"campaign.{action}", who, entity_type="campaign", entity_id=cid, detail={"name": row["name"]})
    return services.run_campaign(cid) if action == "run-now" else {"ok": True}


@app.get("/api/reminders")
def reminders(campaign_id: Optional[int] = None, limit: int = Query(100, le=500), who: Principal = Depends(require("campaign.manage"))):
    with db() as c:
        w, a = ("WHERE l.campaign_id=?", [campaign_id]) if campaign_id else ("", [])
        rows = c.execute(f"""SELECT l.*, al.name, al.prn, cm.name campaign FROM reminder_log l
                             LEFT JOIN alumni al ON al.id=l.alumni_id LEFT JOIN campaigns cm ON cm.id=l.campaign_id
                             {w} ORDER BY l.id DESC LIMIT ?""", a + [limit]).fetchall()
        return {"items": [dict(r) for r in rows]}


# ================================================================ proof documents
@app.post("/api/public/proof", dependencies=[Depends(ratelimit.by_ip("public_write"))])
async def public_proof(token: str = Form(...), career_status: str = Form(...), doc_type: str = Form(...), file: UploadFile = File(...)):
    """The alumnus uploads proof through their personal link. Sent before the main submit, so the existing JSON submit is unchanged."""
    ratelimit.check("public_token", token[:64])
    data = await file.read(config.MAX_DOCUMENT_BYTES + 1)          # never read more than the limit allows
    try:
        with db() as c:
            r = _by_token(c, token)
            doc_id, stale = documents.add_proof(c, storage.get_storage(), r["id"], career_status, doc_type, file.filename, data, file.content_type)
            audit.record(c, "document.upload", None, actor_email="(alumni link)", entity_type="alumni", entity_id=r["id"],
                         detail={"document_id": doc_id, "category": career_status, "doc_type": doc_type, "bytes": len(data)})
            proof = documents.current(c, r["id"])
    except (documents.DocumentError, storage.StorageError) as e:
        raise HTTPException(getattr(e, "status", 422), str(e))
    documents.remove_files(stale)                                  # replaced uploads, removed only after the commit
    return {"ok": True, "proof": proof}


class ReviewIn(BaseModel):
    decision: str
    reason: Optional[str] = Field(None, max_length=500)


@app.get("/api/verification")
def verification_queue(status: str = "PENDING", category: str = "", search: str = "", page: int = 1,
                       page_size: int = Query(25, le=100), who: Principal = Depends(require("verification.review"))):
    if status not in ("all", "PENDING", "APPROVED", "REJECTED") or category not in ("", *documents.CATEGORIES):
        raise HTTPException(422, "Unknown status or category")
    with db() as c:
        return documents.queue(c, status, category, search, page, page_size)


@app.post("/api/documents/{doc_id}/review")
def review_document(doc_id: int, body: ReviewIn, who: Principal = Depends(require("verification.review"))):
    try:
        with db() as c:
            change = documents.review(c, doc_id, who.email, body.decision, body.reason)
            audit.record(c, "document.review", who, entity_type="alumni", entity_id=change["alumni_id"],
                         detail={"document_id": doc_id, "from": change["before"], "to": change["after"], "reason": body.reason})
    except documents.DocumentError as e:
        raise HTTPException(e.status, e.message)
    return {"ok": True, "status": body.decision}


@app.get("/api/documents/{doc_id}/download")
def download_document(doc_id: int, who: Principal = Depends(current_principal)):
    """Staff with review permission, or the alumnus the document belongs to. Everyone else gets 404 (not 403)."""
    with db() as c:
        r = documents.get(c, doc_id)
        if not r or not (who.has("verification.review") or (who.alumni_id is not None and who.alumni_id == r["alumni_id"])):
            raise HTTPException(404, "Document not found")
        audit.record(c, "document.download", who, entity_type="alumni", entity_id=r["alumni_id"], detail={"document_id": doc_id})
    try:
        data = storage.get_storage().get(r["storage_key"])
    except storage.StorageError:
        raise HTTPException(404, "The stored file is missing")
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", r["original_name"])[:100] or "document"
    return Response(data, media_type=r["content_type"], headers={
        "Content-Disposition": f'attachment; filename="{safe}"',
        "X-Content-Type-Options": "nosniff",          # the browser must not guess a different (executable) type
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox"})


@app.get("/api/profile/me/documents")
def my_documents(who: Principal = Depends(require("profile.own.read"))):
    aid = _own_alumni_id(who)
    with db() as c:
        return {"items": documents.history(c, aid, staff=False)}


# ================================================================ personal links (staff)
@app.post("/api/alumni/{aid}/link/{action}")
def alumni_link(aid: int, action: str, who: Principal = Depends(require("alumni.link.manage"))):
    """regenerate: the old link stops working and a new one is issued. revoke: the link is disabled and the person is
    left out of reminders until a new one is generated."""
    if action not in ("regenerate", "revoke"):
        raise HTTPException(404, "Unknown action")
    with db() as c:
        r = c.execute("SELECT id,name FROM alumni WHERE id=?", (aid,)).fetchone()
        if not r:
            raise HTTPException(404, "Not found")
        if action == "regenerate":
            tok = services.regenerate_token(c, aid)
        else:
            services.revoke_token(c, aid)
        audit.record(c, f"alumni.link_{action}", who, entity_type="alumni", entity_id=aid)
        row = c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()
        out = {"link_status": services.token_state(row), "expires_at": row["token_expires_at"]}
        if action == "regenerate":
            out["link"] = f"{config.PUBLIC_URL}/update?token={tok}"
    return out


# ================================================================ profiles and privacy
class VisibilityIn(BaseModel):
    level: str


def _own_alumni_id(who: Principal):
    if not who.alumni_id:
        raise HTTPException(404, "This account is not linked to an alumni record")
    return who.alumni_id


@app.get("/api/profile/me")
def my_profile(who: Principal = Depends(require("profile.own.read"))):
    aid = _own_alumni_id(who)
    with db() as c:
        row = c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "This account is not linked to an alumni record")
        return visibility.shape(c, row, who)


@app.get("/api/profile/me/visibility")
def my_visibility(who: Principal = Depends(require("profile.own.read"))):
    aid = _own_alumni_id(who)
    with db() as c:
        return {"level": visibility.get_level(c, aid), "levels": list(visibility.LEVELS)}


@app.put("/api/profile/me/visibility")
def set_my_visibility(body: VisibilityIn, who: Principal = Depends(require("profile.own.write"))):
    aid = _own_alumni_id(who)
    if not visibility.valid_level(body.level):
        raise HTTPException(422, "level must be one of " + ", ".join(visibility.LEVELS))
    with db() as c:
        before = visibility.get_level(c, aid)
        visibility.set_level(c, aid, body.level, who.email)
        audit.record(c, "profile.visibility", who, entity_type="alumni", entity_id=aid, detail={"from": before, "to": body.level})
    return {"level": body.level}


@app.get("/api/alumni/{aid}/visibility")
def alumni_visibility(aid: int, who: Principal = Depends(require("alumni.read"))):
    """Staff can see the choice an alumnus made; only the alumnus can change it."""
    with db() as c:
        if not c.execute("SELECT 1 FROM alumni WHERE id=?", (aid,)).fetchone():
            raise HTTPException(404, "Not found")
        return {"level": visibility.get_level(c, aid)}


@app.get("/api/profiles/{aid}")
def view_profile(aid: int, request: Request, viewer: Optional[Principal] = Depends(optional_principal)):
    """A profile as the caller is allowed to see it. Anonymous visitors only ever see PUBLIC profiles; a profile the
    caller may not see answers 404, exactly like one that does not exist."""
    if viewer is None:
        ratelimit.check("profile_public", ratelimit.client_ip(request))
    elif not viewer.has("directory.read"):
        raise HTTPException(403, "You do not have permission to do that")
    with db() as c:
        row = c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()
        shaped = visibility.shape(c, row, viewer) if row else None
    if shaped is None:
        raise HTTPException(404, "Profile not found")
    return shaped


class ProfileIn(BaseModel):
    whatsapp: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    professional_domain: Optional[str] = None
    years_experience: Optional[float] = None
    designation: Optional[str] = None
    headline: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    skills: Optional[list[str]] = None
    interests: Optional[list[str]] = None


class EventIn(BaseModel):
    event_type: str
    title: str = Field(max_length=300)
    event_date: Optional[str] = None
    organisation: Optional[str] = Field(None, max_length=300)
    detail: Optional[str] = Field(None, max_length=2000)


class RetractIn(BaseModel):
    reason: str = Field(max_length=300)


def _supplied(model):
    return getattr(model, "model_dump", model.dict)(exclude_unset=True)


def _save_profile(aid, body, who):
    with db() as c:
        if not c.execute("SELECT 1 FROM alumni WHERE id=?", (aid,)).fetchone():
            raise HTTPException(404, "Not found")
        changed = profiles.save(c, aid, _supplied(body), who.email)
        audit.record(c, "profile.update", who, entity_type="alumni", entity_id=aid, detail={"fields": changed})   # names only, never values
        return profiles.get(c, aid)


def _add_event(aid, body, who, source):
    if body.event_type not in careers.USER_TYPES:
        raise HTTPException(422, "Choose one of: " + ", ".join(careers.TYPES[t] for t in careers.USER_TYPES))
    with db() as c:
        if not c.execute("SELECT 1 FROM alumni WHERE id=?", (aid,)).fetchone():
            raise HTTPException(404, "Not found")
        eid = careers.add_event(c, aid, body.event_type, body.title, event_date=body.event_date, organisation=body.organisation,
                                detail=body.detail, source=source, by=who.email)
        audit.record(c, "career.add", who, entity_type="alumni", entity_id=aid, detail={"event_id": eid, "type": body.event_type})
    return {"id": eid}


def _retract_event(aid, eid, body, who):
    with db() as c:
        careers.retract(c, eid, who.email, body.reason, alumni_id=aid)
        audit.record(c, "career.retract", who, entity_type="alumni", entity_id=aid, detail={"event_id": eid})
    return {"ok": True}


@app.put("/api/profile/me/details")
def my_profile_details(body: ProfileIn, who: Principal = Depends(require("profile.own.write"))):
    return _save_profile(_own_alumni_id(who), body, who)


@app.put("/api/alumni/{aid}/profile")
def staff_profile_details(aid: int, body: ProfileIn, who: Principal = Depends(require("alumni.write"))):
    return _save_profile(aid, body, who)


@app.post("/api/profile/me/career-events")
def my_add_event(body: EventIn, who: Principal = Depends(require("profile.own.write"))):
    return _add_event(_own_alumni_id(who), body, who, "PROFILE")


@app.post("/api/alumni/{aid}/career-events")
def staff_add_event(aid: int, body: EventIn, who: Principal = Depends(require("alumni.write"))):
    return _add_event(aid, body, who, "STAFF")


@app.post("/api/profile/me/career-events/{eid}/retract")
def my_retract_event(eid: int, body: RetractIn, who: Principal = Depends(require("profile.own.write"))):
    return _retract_event(_own_alumni_id(who), eid, body, who)


@app.post("/api/alumni/{aid}/career-events/{eid}/retract")
def staff_retract_event(aid: int, eid: int, body: RetractIn, who: Principal = Depends(require("alumni.write"))):
    return _retract_event(aid, eid, body, who)


@app.get("/api/directory")
def member_directory(search: str = "", batch: Optional[int] = Query(None, ge=1990, le=2100), page: int = 1,
                     page_size: int = Query(24, le=60), who: Principal = Depends(require("directory.read"))):
    """Browse alumni who chose to be seen by this viewer's role. Search covers name, organisation, domain, city, country,
    designation and skills. (Richer filters and sorting arrive with Phase 2.)"""
    with db() as c:
        return visibility.directory(c, who, search, batch, page, page_size)


# ================================================================ public alumni portal (token only)
LINK_GONE = {"expired": "This link has expired. Please ask the department to send you a new one.",
             "revoked": "This link has been disabled. Please ask the department to send you a new one."}


def _by_token(c, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token or ""):
        raise HTTPException(404, "This link is not valid")
    r, state = services.lookup_token(c, token)
    if not r:
        raise HTTPException(404, "This link is not valid")
    if state != "active":
        raise HTTPException(410, LINK_GONE[state])      # 410 Gone: the link existed but no longer works
    return r


@app.get("/api/public/form", dependencies=[Depends(ratelimit.by_ip("public_read"))])
def public_form(token: str):
    ratelimit.check("public_token", token[:64])
    with db() as c:
        r = _by_token(c, token)
        best = c.execute("SELECT employer,position,package_lpa FROM offers WHERE alumni_id=? ORDER BY package_lpa DESC LIMIT 1", (r["id"],)).fetchone()
        hs = c.execute("SELECT degree,institution FROM higher_studies WHERE alumni_id=? ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
        ent = c.execute("SELECT company FROM ventures WHERE alumni_id=? ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
        prefill = None
        if best:
            prefill = {"kind": "EMPLOYMENT", "source": "placement", "company": best["employer"], "designation": best["position"]}
        elif hs:
            prefill = {"kind": "HIGHER_STUDIES", "source": "higher studies", "university": hs["institution"], "degree": hs["degree"]}
        elif ent:
            prefill = {"kind": "ENTREPRENEURSHIP", "source": "entrepreneurship", "startup_name": ent["company"]}
        proof = documents.current(c, r["id"])
        return {"name": r["name"], "graduation_year": r["graduation_year"], "prn": r["prn"], "status": r["status"],
                "career_status": r["career_status"], "details": json.loads(r["details"]) if r["details"] else None,
                "prefill": prefill,
                # Phase 1: proof upload + income range. The server owns the lists, so the form never drifts from the rules.
                "requirements": {"proof": config.REQUIRE_PROOF, "income": config.REQUIRE_INCOME_RANGE},
                "income_bands": income.for_form(), "income_band": r["income_band"],
                "proof_types": documents.for_form(), "proof": proof,
                "max_upload_mb": config.MAX_DOCUMENT_BYTES // (1024 * 1024)}


class Submission(BaseModel):
    token: str
    career_status: str
    details: dict
    income_band: Optional[str] = None      # a code from income.BANDS for this career type
    consent: bool = False                  # agrees to proof + income being collected for verification and statistics


REQUIRED = {"EMPLOYMENT": ["company", "designation", "industry"],
            "HIGHER_STUDIES": ["university", "country", "degree", "specialization"],
            "ENTREPRENEURSHIP": ["startup_name", "business_domain", "stage"]}
OPTIONAL = {"EMPLOYMENT": ["notes"], "HIGHER_STUDIES": [], "ENTREPRENEURSHIP": []}
STAGES = ["Idea", "Prototype / MVP", "Early revenue", "Growth"]


@app.post("/api/public/submit", dependencies=[Depends(ratelimit.by_ip("public_write"))])
def public_submit(b: Submission):
    ratelimit.check("public_token", b.token[:64])
    if b.career_status not in REQUIRED:
        raise HTTPException(422, "Choose Placement, Higher Studies or Entrepreneurship")
    clean = {}
    for k in REQUIRED[b.career_status]:
        v = str(b.details.get(k, "")).strip()
        if not v:
            raise HTTPException(422, f"'{k.replace('_', ' ')}' is required")
        if len(v) > 200:
            raise HTTPException(422, f"'{k.replace('_', ' ')}' is too long")
        clean[k] = v
    for k in OPTIONAL[b.career_status]:
        v = str(b.details.get(k, "")).strip()[:1000]
        if v:
            clean[k] = v
    if b.career_status == "ENTREPRENEURSHIP" and clean["stage"] not in STAGES:
        raise HTTPException(422, "Invalid stage")
    if b.income_band:
        if not income.valid(b.career_status, b.income_band):
            raise HTTPException(422, "Choose one of the listed income ranges")
    elif config.REQUIRE_INCOME_RANGE:
        raise HTTPException(422, "Please select your income range: " + income.BANDS[b.career_status][0].lower())
    if (config.REQUIRE_PROOF or config.REQUIRE_INCOME_RANGE or b.income_band) and not b.consent:
        raise HTTPException(422, "Please tick the box to confirm you agree to your proof and income range being used for verification")
    with db() as c:
        r = _by_token(c, b.token)
        if config.REQUIRE_PROOF:
            p = documents.current(c, r["id"])
            if not p:
                raise HTTPException(422, "Please upload a proof of your " + {"EMPLOYMENT": "employment", "HIGHER_STUDIES": "admission",
                                                                         "ENTREPRENEURSHIP": "venture"}[b.career_status])
            if p["category"] != b.career_status:
                raise HTTPException(422, "The proof you uploaded is for a different option. Please upload a proof for your current choice.")
            if p["status"] == documents.REJECTED:
                raise HTTPException(422, f"Your proof was not accepted: {p['rejection_reason']}. Please upload a new one.")
        again = r["status"] == "COMPLETED"
        c.execute("UPDATE alumni SET status='COMPLETED', career_status=?, details=?, submitted_at=datetime('now'),"
                  " income_band=COALESCE(?, income_band), income_updated_at=CASE WHEN ? IS NULL THEN income_updated_at ELSE datetime('now') END,"
                  " verification_consent_at=CASE WHEN ? THEN datetime('now') ELSE verification_consent_at END WHERE id=?",
                  (b.career_status, json.dumps(clean), b.income_band, b.income_band, int(b.consent), r["id"]))
        audit.record(c, "public.submit", None, actor_email="(alumni link)", entity_type="alumni", entity_id=r["id"],
                     detail={"career_status": b.career_status, "resubmission": again, "income_band": b.income_band, "consent": b.consent})
        careers.record_submission(c, r["id"], b.career_status, clean)         # only writes what actually changed
        profiles.fill_from_submission(c, r["id"], b.career_status, clean)    # blanks only; never overwrites a chosen value
    return {"ok": True, "already_submitted": again}
