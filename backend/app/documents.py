"""Proof documents: what may be uploaded, who reviewed it, and the lifecycle of the stored files.

Rules:
  * a proof belongs to one career type (EMPLOYMENT / HIGHER_STUDIES / ENTREPRENEURSHIP) and one allowed document type;
  * a new upload replaces the person's earlier PENDING or REJECTED one (the old file is deleted); APPROVED ones stay as history;
  * staff approve or reject; a rejection needs a reason, which the person sees so they can fix it;
  * the stored file's key is never returned to any client; files are only read through an authorised endpoint;
  * files are removed with the person (and swept if a bulk operation left any behind).

Functions never delete files themselves while a database transaction is open: they *return* the keys, and the caller
removes the files after the commit (`remove_files`). A rolled-back change therefore never loses a file.
"""
import time
from datetime import datetime, timezone

from . import config, storage

CATEGORIES = ("EMPLOYMENT", "HIGHER_STUDIES", "ENTREPRENEURSHIP")
PENDING, APPROVED, REJECTED = "PENDING", "APPROVED", "REJECTED"

PROOF_TYPES = {
    "EMPLOYMENT": [("JOINING_MAIL", "Joining or offer-confirmation email (PDF or screenshot)"),
                   ("OFFICE_ID_CARD", "Company ID card"),
                   ("APPOINTMENT_LETTER", "Appointment letter"),
                   ("OTHER", "Other proof of employment")],
    "HIGHER_STUDIES": [("ADMISSION_LETTER", "Admission or offer letter"),
                       ("UNIVERSITY_ID_CARD", "University ID card"),
                       ("FEE_RECEIPT", "Fee receipt or enrolment confirmation"),
                       ("OTHER", "Other proof of admission")],
    "ENTREPRENEURSHIP": [("STARTUP_REGISTRATION", "Incorporation, Udyam or GST registration"),
                         ("BUSINESS_PROOF", "Business proof: website, invoice, bank or funding letter"),
                         ("OTHER", "Other proof that you run the venture")],
}
_LABELS = {(cat, code): label for cat, items in PROOF_TYPES.items() for code, label in items}


class DocumentError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def type_label(category, doc_type):
    return _LABELS.get((category, doc_type), doc_type)


def for_form():
    return {cat: [{"code": c, "label": l} for c, l in items] for cat, items in PROOF_TYPES.items()}


# ---------------------------------------------------------------- shapes (storage_key is never included)
def _row(r, staff=False):
    d = {"id": r["id"], "category": r["category"], "doc_type": r["doc_type"], "doc_label": type_label(r["category"], r["doc_type"]),
         "original_name": r["original_name"], "content_type": r["content_type"], "size_bytes": r["size_bytes"], "status": r["status"],
         "rejection_reason": r["rejection_reason"], "uploaded_at": r["uploaded_at"], "reviewed_at": r["reviewed_at"],
         "superseded": bool(r["superseded_at"])}
    if staff:
        d["reviewed_by"] = r["reviewed_by"]
        d["sha256"] = r["sha256"]
    return d


def current(c, alumni_id, staff=False):
    """The person's live proof (newest that has not been replaced), or None."""
    r = c.execute("SELECT * FROM verification_documents WHERE alumni_id=? AND superseded_at IS NULL ORDER BY id DESC LIMIT 1",
                  (alumni_id,)).fetchone()
    return _row(r, staff) if r else None


def history(c, alumni_id, staff=True):
    return [_row(r, staff) for r in c.execute("SELECT * FROM verification_documents WHERE alumni_id=? ORDER BY id DESC", (alumni_id,))]


def status_of(c, alumni_id):
    d = current(c, alumni_id)
    return d["status"] if d else "MISSING"


# ---------------------------------------------------------------- upload
def add_proof(c, store, alumni_id, category, doc_type, filename, data, declared_type=None):
    """Validate and store a new proof. Returns (doc_id, keys_to_delete_after_commit). Raises DocumentError / StorageError."""
    if category not in PROOF_TYPES:
        raise DocumentError("Choose Placement, Higher Studies or Entrepreneurship first")
    if doc_type not in {code for code, _ in PROOF_TYPES[category]}:
        raise DocumentError("Choose what kind of proof you are uploading")
    live = c.execute("SELECT COUNT(*) n FROM verification_documents WHERE alumni_id=? AND superseded_at IS NULL", (alumni_id,)).fetchone()["n"]
    stale = c.execute("SELECT id, storage_key FROM verification_documents WHERE alumni_id=? AND superseded_at IS NULL AND status<>?",
                      (alumni_id, APPROVED)).fetchall()
    if live - len(stale) >= config.MAX_PROOFS_PER_ALUMNI:
        raise DocumentError("Too many documents are already on file. Please contact the department.", 409)
    saved = store.save_upload(filename, data, declared_type)             # raises StorageError on a bad file
    now = _now()
    for old in stale:                                                    # the new upload replaces anything not yet accepted
        c.execute("UPDATE verification_documents SET superseded_at=? WHERE id=?", (now, old["id"]))
    doc_id = c.execute(
        "INSERT INTO verification_documents(alumni_id,category,doc_type,storage_key,original_name,content_type,size_bytes,sha256,status,uploaded_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (alumni_id, category, doc_type, saved.key, saved.original_name, saved.content_type, saved.size, saved.sha256, PENDING, now)).lastrowid
    return doc_id, [o["storage_key"] for o in stale]


# ---------------------------------------------------------------- review
def review(c, doc_id, reviewer, decision, reason=None):
    if decision not in (APPROVED, REJECTED):
        raise DocumentError("decision must be APPROVED or REJECTED")
    r = c.execute("SELECT * FROM verification_documents WHERE id=?", (doc_id,)).fetchone()
    if not r:
        raise DocumentError("Document not found", 404)
    if r["superseded_at"]:
        raise DocumentError("This document was replaced by a newer upload", 409)
    reason = (reason or "").strip()
    if decision == REJECTED and len(reason) < 5:
        raise DocumentError("Give the person a reason (at least 5 characters) so they know what to fix")
    c.execute("UPDATE verification_documents SET status=?, rejection_reason=?, reviewed_by=?, reviewed_at=? WHERE id=?",
              (decision, reason[:500] if decision == REJECTED else None, reviewer, _now(), doc_id))
    return {"before": r["status"], "after": decision, "alumni_id": r["alumni_id"]}


def get(c, doc_id):
    return c.execute("SELECT * FROM verification_documents WHERE id=?", (doc_id,)).fetchone()


def queue(c, status="PENDING", category="", search="", page=1, page_size=25):
    where, args = ["d.superseded_at IS NULL"], []
    if status and status != "all":
        where.append("d.status=?"); args.append(status)
    if category:
        where.append("d.category=?"); args.append(category)
    if search.strip():
        where.append("(a.name LIKE ? OR a.prn LIKE ?)"); args += [f"%{search.strip()}%"] * 2
    w = " AND ".join(where)
    base = f"FROM verification_documents d JOIN alumni a ON a.id=d.alumni_id WHERE {w}"
    total = c.execute(f"SELECT COUNT(*) n {base}", args).fetchone()["n"]
    rows = c.execute(f"SELECT d.*, a.name, a.prn, a.graduation_year, a.income_band {base} ORDER BY d.uploaded_at ASC LIMIT ? OFFSET ?",
                     args + [page_size, (max(page, 1) - 1) * page_size]).fetchall()
    items = []
    for r in rows:
        d = _row(r, staff=True)
        d.update(alumni_id=r["alumni_id"], name=r["name"], prn=r["prn"], graduation_year=r["graduation_year"])
        items.append(d)
    counts = {s: c.execute("SELECT COUNT(*) n FROM verification_documents WHERE superseded_at IS NULL AND status=?", (s,)).fetchone()["n"]
              for s in (PENDING, APPROVED, REJECTED)}
    return {"items": items, "total": total, "page": page, "page_size": page_size, "counts": counts}


# ---------------------------------------------------------------- file lifecycle
def purge_alumni(c, alumni_id):
    """Delete the person's document rows and return their file keys (caller removes the files after commit)."""
    keys = [r["storage_key"] for r in c.execute("SELECT storage_key FROM verification_documents WHERE alumni_id=?", (alumni_id,))]
    c.execute("DELETE FROM verification_documents WHERE alumni_id=?", (alumni_id,))
    return keys


def purge_all(c):
    keys = [r["storage_key"] for r in c.execute("SELECT storage_key FROM verification_documents")]
    c.execute("DELETE FROM verification_documents")
    return keys


def remove_files(keys, store=None):
    store = store or storage.get_storage()
    for k in keys:
        try:
            store.delete(k)
        except storage.StorageError:
            pass


def sweep_orphans(c, store=None, grace_seconds=600):
    """Delete stored files that no row refers to (left by a crash or a bulk delete). Files newer than `grace_seconds`
    are left alone because an upload may be between 'file written' and 'row committed'. Returns how many were removed."""
    store = store or storage.get_storage()
    known = {r["storage_key"] for r in c.execute("SELECT storage_key FROM verification_documents")}
    cutoff, n = time.time() - grace_seconds, 0
    for key, mtime in store.list_keys():
        if key not in known and mtime < cutoff:
            store.delete(key)
            n += 1
    return n
