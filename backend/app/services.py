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


def alumnus_dict(c, row, with_offers=True):
    d = dict(row)
    d["details"] = json.loads(d["details"]) if d.get("details") else None
    cutoff = overdue_cutoff(c)
    d["overdue"] = bool(cutoff and d["status"] == "PENDING" and cutoff < now().strftime("%Y-%m-%d"))
    if with_offers:
        d["offers"] = [dict(o) for o in c.execute("SELECT * FROM offers WHERE alumni_id=? ORDER BY package_lpa DESC", (d["id"],))]
        d["best_package"] = max([o["package_lpa"] or 0 for o in d["offers"]], default=0)
    return d


def import_students(c, students, graduation_year, replace=False, final_year_students=None, import_id=None):
    if replace:
        for t in ("reminder_log", "undo_actions", "offers", "alumni"):
            c.execute(f"DELETE FROM {t}")
    added = updated = offers_added = 0
    for s in students:
        row = c.execute("SELECT id FROM alumni WHERE prn=?", (s["prn"],)).fetchone()
        if row:
            aid = row["id"]
            c.execute("UPDATE alumni SET name=?, class_div=?, phone=?, email=?, sr_no=?, graduation_year=? WHERE id=?",
                      (s["name"], s["class_div"], s["phone"], s["email"], s["sr_no"], graduation_year, aid))
            updated += 1
        else:
            aid = c.execute("INSERT INTO alumni(sr_no,name,prn,class_div,phone,email,graduation_year,token) VALUES(?,?,?,?,?,?,?,?)",
                            (s["sr_no"], s["name"], s["prn"], s["class_div"], s["phone"], s["email"], graduation_year, new_token())).lastrowid
            added += 1
        if import_id:   # remember which file this alumnus came from (an alumnus can belong to several files)
            c.execute("INSERT OR IGNORE INTO import_batch_alumni(import_id,alumni_id) VALUES(?,?)", (import_id, aid))
        have = {(o["employer"].lower(), o["package_lpa"], (o["position"] or "").lower())
                for o in c.execute("SELECT employer,package_lpa,position FROM offers WHERE alumni_id=?", (aid,))}
        for o in s["offers"]:
            key = (o["employer"].lower(), o["package_lpa"], (o["position"] or "").lower())
            if key in have:
                continue
            have.add(key)
            c.execute("INSERT INTO offers(alumni_id,employer,package_lpa,position,letter_ref,letter_link) VALUES(?,?,?,?,?,?)",
                      (aid, o["employer"], o["package_lpa"], o["position"], o["letter_ref"], o["letter_link"]))
            offers_added += 1
    if final_year_students:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (f"final_year_students:{graduation_year}", str(final_year_students)))
    return {"added": added, "updated": updated, "offers_added": offers_added}


def push_undo(c, type_, payload, label):
    c.execute("INSERT INTO undo_actions(type,payload,label) VALUES(?,?,?)", (type_, json.dumps(payload), label))


def snapshot(c, aid):
    a = c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()
    return {"alumni": dict(a), "offers": [dict(o) for o in c.execute("SELECT * FROM offers WHERE alumni_id=?", (aid,))]}


def restore(c, snap):
    a = snap["alumni"]
    cols = list(a.keys())
    c.execute(f"INSERT INTO alumni({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [a[k] for k in cols])
    for o in snap["offers"]:
        oc = list(o.keys())
        c.execute(f"INSERT INTO offers({','.join(oc)}) VALUES({','.join('?' * len(oc))})", [o[k] for k in oc])


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
        """SELECT b.id, b.filename, b.graduation_year, b.created_at, COUNT(m.alumni_id) total
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
        d["employer"] = offers[0]["employer"] if offers else ""
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
    return {"summary": s, "by_batch": by_batch, "career": career, "placement": placement}
