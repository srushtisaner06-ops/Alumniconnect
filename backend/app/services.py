import json
import statistics
from datetime import datetime, timedelta, timezone

from . import engine, notifier
from .db import db
from .security import new_token


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if s else None


# ---------------------------------------------------------------- alumni
def overdue_cutoff(c):
    r = c.execute("SELECT MIN(deadline) d FROM campaigns WHERE deadline IS NOT NULL AND status!='DRAFT'").fetchone()
    return r["d"]


CATEGORY_TABLES = {"PLACEMENT": "offers", "HIGHER_STUDIES": "higher_studies", "ENTREPRENEURSHIP": "ventures"}


def alumnus_dict(c, row, with_offers=True):
    d = dict(row)
    d["details"] = json.loads(d["details"]) if d.get("details") else None
    cutoff = overdue_cutoff(c)
    d["overdue"] = bool(cutoff and d["status"] == "PENDING" and cutoff < now().strftime("%Y-%m-%d"))
    if with_offers:
        d["offers"] = [dict(o) for o in c.execute("SELECT * FROM offers WHERE alumni_id=? ORDER BY package_lpa DESC", (d["id"],))]
        d["best_package"] = max([o["package_lpa"] or 0 for o in d["offers"]], default=0)
        d["higher_studies"] = [dict(h) for h in c.execute("SELECT * FROM higher_studies WHERE alumni_id=? ORDER BY id", (d["id"],))]
        d["ventures"] = [dict(v) for v in c.execute("SELECT * FROM ventures WHERE alumni_id=? ORDER BY id", (d["id"],))]
        # Which of the three record categories this alumnus appears in (placement / higher studies / entrepreneurship)
        d["categories"] = [cat for cat, key in (("PLACEMENT", "offers"), ("HIGHER_STUDIES", "higher_studies"),
                                                ("ENTREPRENEURSHIP", "ventures")) if d[key]]
    return d


def import_students(c, students, graduation_year, replace=False, final_year_students=None, import_id=None):
    if replace:
        for t in ("reminder_log", "undo_actions", "offers", "higher_studies", "ventures", "alumni"):
            c.execute(f"DELETE FROM {t}")
    added = updated = offers_added = hs_added = ventures_added = 0
    for s in students:
        row = c.execute("SELECT id FROM alumni WHERE prn=?", (s["prn"],)).fetchone()
        tg = s.get("telegram_chat_id")  # optional import column; blank never erases a chat already linked
        if row:
            aid = row["id"]
            c.execute("UPDATE alumni SET name=?, class_div=?, phone=?, email=?, sr_no=?, graduation_year=?, "
                      "telegram_chat_id=COALESCE(?, telegram_chat_id) WHERE id=?",
                      (s["name"], s["class_div"], s["phone"], s["email"], s["sr_no"], graduation_year, tg, aid))
            updated += 1
        else:
            aid = c.execute("INSERT INTO alumni(sr_no,name,prn,class_div,phone,email,telegram_chat_id,graduation_year,token) VALUES(?,?,?,?,?,?,?,?,?)",
                            (s["sr_no"], s["name"], s["prn"], s["class_div"], s["phone"], s["email"], tg, graduation_year, new_token())).lastrowid
            added += 1
        if import_id:   # remember which file this alumnus came from (an alumnus can belong to several files)
            c.execute("INSERT OR IGNORE INTO import_batch_alumni(import_id,alumni_id) VALUES(?,?)", (import_id, aid))
        have = {(o["employer"].lower(), o["package_lpa"], (o["position"] or "").lower())
                for o in c.execute("SELECT employer,package_lpa,position FROM offers WHERE alumni_id=?", (aid,))}
        for o in s.get("offers", []):
            key = (o["employer"].lower(), o["package_lpa"], (o["position"] or "").lower())
            if key in have:
                continue
            have.add(key)
            c.execute("INSERT INTO offers(alumni_id,employer,package_lpa,position,letter_ref,letter_link) VALUES(?,?,?,?,?,?)",
                      (aid, o["employer"], o["package_lpa"], o["position"], o["letter_ref"], o["letter_link"]))
            offers_added += 1
        have_hs = {((h["degree"] or "").lower(), (h["institution"] or "").lower())
                   for h in c.execute("SELECT degree,institution FROM higher_studies WHERE alumni_id=?", (aid,))}
        for h in s.get("higher_studies", []):
            key = (h["degree"].lower(), h["institution"].lower())
            if key in have_hs:
                continue
            have_hs.add(key)
            c.execute("INSERT INTO higher_studies(alumni_id,degree,institution,letter_link) VALUES(?,?,?,?)",
                      (aid, h["degree"], h["institution"], h["letter_link"]))
            hs_added += 1
        have_v = {((v["company"] or "").lower(), (v["registration_no"] or "").lower())
                  for v in c.execute("SELECT company,registration_no FROM ventures WHERE alumni_id=?", (aid,))}
        for v in s.get("ventures", []):
            key = (v["company"].lower(), v["registration_no"].lower())
            if key in have_v:
                continue
            have_v.add(key)
            c.execute("INSERT INTO ventures(alumni_id,company,registration_no,website,letter_link) VALUES(?,?,?,?,?)",
                      (aid, v["company"], v["registration_no"], v["website"], v["letter_link"]))
            ventures_added += 1
    if final_year_students:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (f"final_year_students:{graduation_year}", str(final_year_students)))
    return {"added": added, "updated": updated, "offers_added": offers_added,
            "higher_studies_added": hs_added, "ventures_added": ventures_added}


def push_undo(c, type_, payload, label):
    c.execute("INSERT INTO undo_actions(type,payload,label) VALUES(?,?,?)", (type_, json.dumps(payload), label))


def snapshot(c, aid):
    a = c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()
    snap = {"alumni": dict(a)}
    for table in CATEGORY_TABLES.values():
        snap[table] = [dict(o) for o in c.execute(f"SELECT * FROM {table} WHERE alumni_id=?", (aid,))]
    return snap


def restore(c, snap):
    a = snap["alumni"]
    cols = list(a.keys())
    c.execute(f"INSERT INTO alumni({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [a[k] for k in cols])
    for table in CATEGORY_TABLES.values():          # older undo entries only hold "offers"
        for o in snap.get(table, []):
            oc = list(o.keys())
            c.execute(f"INSERT INTO {table}({','.join(oc)}) VALUES({','.join('?' * len(oc))})", [o[k] for k in oc])


def undo_last(c):
    rows = c.execute("SELECT id,type,payload,label FROM undo_actions ORDER BY id").fetchall()
    top = engine.undo_top([r["id"] for r in rows])
    if top is None:
        return None
    r = next(x for x in rows if x["id"] == top)
    p = json.loads(r["payload"])
    if r["type"] == "delete_alumni":
        restore(c, p)
    elif r["type"] == "set_unsubscribed":
        c.execute("UPDATE alumni SET unsubscribed=? WHERE id=?", (p["previous"], p["id"]))
    c.execute("DELETE FROM undo_actions WHERE id=?", (top,))
    return r["label"]


# ---------------------------------------------------------------- recipient selection
MAX_SELECTION_IDS = 5000


def normalize_selection(raw):
    """Clean a client-supplied selection into {"all", "batches", "import_ids", "alumni_ids"}."""
    raw = raw or {}

    def ints(key, lo=1, hi=10 ** 9):
        out = []
        for v in raw.get(key) or []:
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if lo <= n <= hi and n not in out:
                out.append(n)
        return out[:MAX_SELECTION_IDS]

    return {"all": bool(raw.get("all")), "batches": ints("batches", 1990, 2100),
            "import_ids": ints("import_ids"), "alumni_ids": ints("alumni_ids")}


def selection_is_empty(sel):
    return not sel["all"] and not (sel["batches"] or sel["import_ids"] or sel["alumni_ids"])


def _chunks(ids, size=500):          # stay well under SQLite's bound-variable limit
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


def _marks(chunk):
    return ",".join("?" * len(chunk))


def resolve_selection(c, sel):
    """Alumni ids for a selection. Returns a set, so overlapping groups never produce a duplicate recipient."""
    if sel["all"]:
        return {r["id"] for r in c.execute("SELECT id FROM alumni")}
    out = set()
    for ch in _chunks(sel["batches"]):
        out |= {r["id"] for r in c.execute(f"SELECT id FROM alumni WHERE graduation_year IN ({_marks(ch)})", ch)}
    for ch in _chunks(sel["import_ids"]):
        out |= {r["alumni_id"] for r in c.execute(f"SELECT alumni_id FROM import_batch_alumni WHERE import_id IN ({_marks(ch)})", ch)}
    for ch in _chunks(sel["alumni_ids"]):
        out |= {r["id"] for r in c.execute(f"SELECT id FROM alumni WHERE id IN ({_marks(ch)})", ch)}
    return out


def get_selection(c, camp_id):
    """The campaign's saved audience, or None for campaigns created before this feature (= everyone)."""
    r = c.execute("SELECT config FROM campaign_selection WHERE campaign_id=?", (camp_id,)).fetchone()
    return normalize_selection(json.loads(r["config"])) if r else None


def save_selection(c, camp_id, sel):
    c.execute("INSERT INTO campaign_selection(campaign_id,config) VALUES(?,?) "
              "ON CONFLICT(campaign_id) DO UPDATE SET config=excluded.config", (camp_id, json.dumps(sel)))


def campaign_recipient_ids(c, camp_id):
    """Set of alumni ids the campaign may contact, or None = no restriction."""
    sel = get_selection(c, camp_id)
    return None if sel is None else resolve_selection(c, sel)


def people_for(c, ids):
    out = []
    for ch in _chunks(list(ids)):
        out += [dict(r) for r in c.execute(f"SELECT id,name,prn,graduation_year FROM alumni WHERE id IN ({_marks(ch)}) ORDER BY name", ch)]
    return out


def preview_recipients(c, sel, channel, max_attempts):
    """Live counts shown before a campaign starts. Buckets are exclusive and add up to `selected`."""
    ids = sorted(resolve_selection(c, sel))
    out = {"selected": len(ids), "eligible": 0, "completed": 0, "unsubscribed": 0, "no_contact": 0, "attempts_used": 0}
    camp = {"channel": channel}
    for ch in _chunks(ids):
        for a in c.execute(f"SELECT * FROM alumni WHERE id IN ({_marks(ch)})", ch):
            if a["status"] == "COMPLETED":
                out["completed"] += 1
            elif a["unsubscribed"]:
                out["unsubscribed"] += 1
            elif not _channels(camp, a):
                out["no_contact"] += 1          # no usable email / Telegram chat id for this channel
            elif a["reminders_sent"] >= max_attempts:
                out["attempts_used"] += 1
            else:
                out["eligible"] += 1
    return out


def recipient_options(c):
    batches = [dict(r) for r in c.execute(
        "SELECT graduation_year year, COUNT(*) total FROM alumni GROUP BY graduation_year ORDER BY graduation_year DESC")]
    imports = [dict(r) for r in c.execute(
        """SELECT b.id, b.filename, b.graduation_year, b.category, b.created_at, COUNT(m.alumni_id) total
           FROM import_batches b LEFT JOIN import_batch_alumni m ON m.import_id=b.id GROUP BY b.id ORDER BY b.id DESC""")]
    return {"batches": batches, "imports": imports}


# ---------------------------------------------------------------- reminder worker
def _priority(a, offers):
    days = (now() - (parse_ts(a["created_at"]) or now())).days
    missing = sum(1 for o in offers[:1] if not o["position"]) + sum(1 for o in offers[:1] if not o["letter_link"])
    return days + 10 * missing + 5 * a["reminders_sent"]


def _channels(camp, a):
    out = []
    if camp["channel"] in ("email", "both") and a["email"]:
        out.append("email")
    if camp["channel"] in ("telegram", "both") and a["telegram_chat_id"]:
        out.append("telegram")
    return out


def _other_org(c, aid):
    """Organisation to show in {{employer}} for alumni with no placement: their university or their company."""
    r = c.execute("SELECT institution o FROM higher_studies WHERE alumni_id=? ORDER BY id LIMIT 1", (aid,)).fetchone() \
        or c.execute("SELECT company o FROM ventures WHERE alumni_id=? ORDER BY id LIMIT 1", (aid,)).fetchone()
    return r["o"] if r else ""


def eligible(c, camp):
    t = now()
    out = []
    sel = campaign_recipient_ids(c, camp["id"])      # None = everyone (legacy campaigns)
    for a in c.execute("SELECT * FROM alumni WHERE status='PENDING' AND unsubscribed=0 AND reminders_sent<?", (camp["max_attempts"],)).fetchall():
        if sel is not None and a["id"] not in sel:
            continue
        last = parse_ts(a["last_reminder_at"])
        if last and t - last < timedelta(hours=camp["interval_hours"]):
            continue
        if not _channels(camp, a):
            continue
        offers = c.execute("SELECT * FROM offers WHERE alumni_id=? ORDER BY package_lpa DESC", (a["id"],)).fetchall()
        d = dict(a)
        d["priority"] = _priority(a, offers)
        d["employer"] = offers[0]["employer"] if offers else _other_org(c, a["id"])
        out.append(d)
    return out


def _consecutive_failures(c, camp_id, aid):
    last_ok = c.execute("SELECT COALESCE(MAX(id),0) m FROM reminder_log WHERE campaign_id=? AND alumni_id=? AND status IN ('SENT','SIMULATED')",
                        (camp_id, aid)).fetchone()["m"]
    return c.execute("SELECT COUNT(*) n FROM reminder_log WHERE campaign_id=? AND alumni_id=? AND status='FAILED' AND id>?",
                     (camp_id, aid, last_ok)).fetchone()["n"]


MAX_RETRIES = 3


def eligible_total(c, camp):
    """Alumni who could still be reminded now or later (ignores the interval)."""
    n = 0
    sel = campaign_recipient_ids(c, camp["id"])
    for a in c.execute("SELECT * FROM alumni WHERE status='PENDING' AND unsubscribed=0 AND reminders_sent<?", (camp["max_attempts"],)).fetchall():
        if sel is not None and a["id"] not in sel:
            continue
        if _channels(camp, a):
            n += 1
    return n


def run_campaign(camp_id):
    """One worker pass for a campaign: processes the first batch. Safe to call repeatedly."""
    result = {"sent": 0, "simulated": 0, "failed": 0, "skipped": 0, "remaining": 0}
    key = {"SENT": "sent", "SIMULATED": "simulated", "FAILED": "failed", "SKIPPED": "skipped"}
    with db() as c:
        camp = c.execute("SELECT * FROM campaigns WHERE id=?", (camp_id,)).fetchone()
        if not camp or camp["status"] != "RUNNING":
            return result
        elig = eligible(c, camp)
        sched = engine.schedule([{"id": a["id"], "priority": a["priority"]} for a in elig], camp["batch_size"])
        batch = sched["batches"][0] if sched["batches"] else []
        by_id = {a["id"]: a for a in elig}
        result["remaining"] = len(elig) - len(batch)
        for aid in batch:
            fresh = c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()  # latest status, right before sending
            if fresh is None or fresh["status"] != "PENDING" or fresh["unsubscribed"]:
                c.execute("INSERT INTO reminder_log(campaign_id,alumni_id,channel,status,attempt,error) VALUES(?,?,?,?,?,?)",
                          (camp_id, aid, "-", "SKIPPED", 0, "completed or unsubscribed"))
                result["skipped"] += 1
                continue
            a = dict(by_id[aid])
            attempt = fresh["reminders_sent"] + 1
            chans, outcomes = _channels(camp, a), []
            for ch in chans:
                err = None
                try:
                    if ch == "email":
                        subj, body = notifier.render(camp["email_subject"], a), notifier.render(camp["email_body"], a)
                        if notifier.email_configured():
                            notifier.send_email(a["email"], subj, body)
                            st = "SENT"
                        else:
                            st = "SIMULATED"
                    else:
                        body = notifier.render(camp["telegram_body"], a)
                        if notifier.telegram_configured():
                            notifier.send_telegram(a["telegram_chat_id"], body)
                            st = "SENT"
                        else:
                            st = "SIMULATED"
                except notifier.PermanentError as e:
                    st, err = "SKIPPED", str(e)
                    c.execute("UPDATE alumni SET reminders_sent=? WHERE id=?", (camp["max_attempts"], aid))  # invalid contact: stop
                except Exception as e:
                    st, err = "FAILED", str(e)[:200]
                c.execute("INSERT INTO reminder_log(campaign_id,alumni_id,channel,status,attempt,error) VALUES(?,?,?,?,?,?)",
                          (camp_id, aid, ch, st, attempt, err))
                outcomes.append(st)
                result[key[st]] += 1
            ok = any(o in ("SENT", "SIMULATED") for o in outcomes)
            gave_up = bool(outcomes) and all(o == "FAILED" for o in outcomes) and \
                _consecutive_failures(c, camp_id, aid) >= MAX_RETRIES * len(chans)
            if ok or gave_up:
                c.execute("UPDATE alumni SET reminders_sent=reminders_sent+1, last_reminder_at=? WHERE id=? AND reminders_sent<?",
                          (iso(now()), aid, camp["max_attempts"]))
        if eligible_total(c, camp) == 0:
            c.execute("UPDATE campaigns SET status='COMPLETED' WHERE id=?", (camp_id,))
    return result


def poll_telegram():
    """Link Telegram chats to alumni. An alumnus taps t.me/<bot>?start=<token> and presses Start;
    Telegram delivers '/start <token>' and we store that chat's id. Returns how many were linked."""
    if not notifier.telegram_configured():
        return 0
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key='telegram_offset'").fetchone()
    offset = int(row["value"]) if row else 0
    updates = notifier.fetch_telegram_updates(offset)
    if not updates:
        return 0
    linked, replies = 0, []
    with db() as c:
        for u in updates:
            offset = max(offset, u["update_id"] + 1)
            m = u.get("message") or {}
            chat = m.get("chat") or {}
            parts = (m.get("text") or "").strip().split(maxsplit=1)
            if chat.get("type") != "private" or not parts or not parts[0].startswith("/start"):
                continue
            token = parts[1].strip() if len(parts) > 1 else ""
            a = c.execute("SELECT id,name FROM alumni WHERE token=?", (token,)).fetchone() if token else None
            chat_id = str(chat["id"])
            if a:
                c.execute("UPDATE alumni SET telegram_chat_id=? WHERE id=?", (chat_id, a["id"]))
                replies.append((chat_id, f"Hi {a['name']}, you are connected. You will receive reminders here."))
                linked += 1
            else:
                replies.append((chat_id, "Please open the personal 'Connect Telegram' link from your email to link this chat."))
        c.execute("INSERT INTO settings(key,value) VALUES('telegram_offset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (str(offset),))
    for chat_id, text in replies:
        try:
            notifier.send_telegram(chat_id, text)
        except Exception as e:
            print("telegram reply failed:", e)
    return linked


def run_all_running():
    with db() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM campaigns WHERE status='RUNNING'")]
    return {i: run_campaign(i) for i in ids}


# ---------------------------------------------------------------- analytics
def summary(c):
    total = c.execute("SELECT COUNT(*) n FROM alumni").fetchone()["n"]
    done = c.execute("SELECT COUNT(*) n FROM alumni WHERE status='COMPLETED'").fetchone()["n"]
    cutoff = overdue_cutoff(c)
    overdue = 0
    if cutoff and cutoff < now().strftime("%Y-%m-%d"):
        overdue = total - done
    return {"total": total, "completed": done, "pending": total - done - overdue, "overdue": overdue,
            "completion_pct": round(100 * done / total, 1) if total else 0}


def analytics(c):
    s = summary(c)
    by_batch = [dict(r) for r in c.execute(
        "SELECT graduation_year year, COUNT(*) total, COALESCE(SUM(status='COMPLETED'),0) completed FROM alumni GROUP BY graduation_year ORDER BY graduation_year")]
    career = {"EMPLOYMENT": 0, "HIGHER_STUDIES": 0, "ENTREPRENEURSHIP": 0}
    for r in c.execute("SELECT career_status, COUNT(*) n FROM alumni WHERE status='COMPLETED' GROUP BY career_status"):
        if r["career_status"] in career:
            career[r["career_status"]] = r["n"]

    studs = c.execute("""SELECT a.id, a.graduation_year y, MAX(o.package_lpa) best, COUNT(o.id) n
                         FROM alumni a JOIN offers o ON o.alumni_id=a.id GROUP BY a.id""").fetchall()
    packages = sorted(r["best"] for r in studs if r["best"] is not None)
    offers_total = c.execute("SELECT COUNT(*) n FROM offers").fetchone()["n"]
    employers = [dict(r) for r in c.execute(
        "SELECT employer, COUNT(DISTINCT alumni_id) students, MAX(package_lpa) top_package FROM offers GROUP BY employer ORDER BY students DESC, top_package DESC LIMIT 8")]
    bands = [("< 5", 0, 5), ("5 – 8", 5, 8), ("8 – 12", 8, 12), ("12 – 20", 12, 20), ("20+", 20, 1e9)]
    band_counts = [{"band": b, "students": sum(1 for p in packages if lo <= p < hi)} for b, lo, hi in bands]
    years = [r["y"] for r in studs]
    fs = None
    if years:
        v = c.execute("SELECT value FROM settings WHERE key=?", (f"final_year_students:{max(years)}",)).fetchone()
        fs = int(v["value"]) if v else None
    placed = len(studs)
    placement = {
        "students_placed": placed, "offers": offers_total, "multi_offer_students": sum(1 for r in studs if r["n"] > 1),
        "avg_package": round(sum(packages) / len(packages), 2) if packages else 0,
        "median_package": round(statistics.median(packages), 2) if packages else 0,
        "highest_package": max(packages) if packages else 0,
        "final_year_students": fs,
        "placement_index": round(100 * placed / fs, 2) if fs else None,
        "top_employers": employers, "package_bands": band_counts}

    # ---- higher studies (Table 4.6.2) and entrepreneurship (Table 4.6.3)
    hs_students = c.execute("SELECT COUNT(DISTINCT alumni_id) n FROM higher_studies").fetchone()["n"]
    higher = {
        "students": hs_students,
        "records": c.execute("SELECT COUNT(*) n FROM higher_studies").fetchone()["n"],
        "top_institutions": [dict(r) for r in c.execute(
            "SELECT institution, COUNT(DISTINCT alumni_id) students FROM higher_studies GROUP BY institution ORDER BY students DESC, institution LIMIT 8")],
        "degrees": [dict(r) for r in c.execute(
            "SELECT degree, COUNT(DISTINCT alumni_id) students FROM higher_studies GROUP BY degree ORDER BY students DESC, degree LIMIT 8")]}
    ent_students = c.execute("SELECT COUNT(DISTINCT alumni_id) n FROM ventures").fetchone()["n"]
    entrepreneurship = {
        "students": ent_students,
        "ventures": c.execute("SELECT COUNT(*) n FROM ventures").fetchone()["n"],
        "companies": [dict(r) for r in c.execute(
            """SELECT v.company, v.registration_no, v.website, a.name founder FROM ventures v JOIN alumni a ON a.id=v.alumni_id
               ORDER BY v.id DESC LIMIT 8""")]}

    # Placement index exactly as the sheet's Summary tab defines it: (X + Y + Z) / FS, where X, Y, Z count
    # students placed / in higher studies / in entrepreneurship. A student in two categories counts once.
    any_rec = c.execute("""SELECT a.graduation_year y, COUNT(*) n FROM alumni a WHERE
        EXISTS(SELECT 1 FROM offers WHERE alumni_id=a.id) OR EXISTS(SELECT 1 FROM higher_studies WHERE alumni_id=a.id)
        OR EXISTS(SELECT 1 FROM ventures WHERE alumni_id=a.id) GROUP BY a.graduation_year ORDER BY a.graduation_year DESC""").fetchall()
    total_unique = sum(r["n"] for r in any_rec)
    fs_all = None
    if any_rec:
        v = c.execute("SELECT value FROM settings WHERE key=?", (f"final_year_students:{any_rec[0]['y']}",)).fetchone()
        fs_all = int(v["value"]) if v else None
    progression = {"final_year_students": fs_all, "placed": placed, "higher_studies": hs_students,
                   "entrepreneurship": ent_students, "total": total_unique,
                   "index": round(100 * total_unique / fs_all, 2) if fs_all else None}
    return {"summary": s, "by_batch": by_batch, "career": career, "placement": placement,
            "higher_studies": higher, "entrepreneurship": entrepreneurship, "progression": progression}
