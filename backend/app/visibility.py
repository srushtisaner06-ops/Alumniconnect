"""Profile visibility (privacy by default).

Levels, from most to least private:

  PRIVATE      only the alumnus and staff (admin / faculty)
  ALUMNI_ONLY  + other alumni
  INSTITUTION  + students (everyone signed in to this institution)
  PUBLIC       + anonymous visitors

Staff can always see records: the department holds them for accreditation, and that is a different purpose from
networking visibility. Everyone else only ever receives the allow-listed `SHARED_FIELDS`. Salary, PRN, documents and
contact details are never in that list, whatever the level. Contact sharing is decided separately (accepted
connection / explicit consent) in Phase 3. Anything not listed is withheld, so a field added to the alumni table later
is private until someone deliberately allows it here.
"""
from datetime import datetime, timezone

from . import careers, profiles, rbac

PRIVATE, ALUMNI_ONLY, INSTITUTION, PUBLIC = "PRIVATE", "ALUMNI_ONLY", "INSTITUTION", "PUBLIC"
LEVELS = (PRIVATE, ALUMNI_ONLY, INSTITUTION, PUBLIC)
DEFAULT_LEVEL = PRIVATE

# Roles that may see a profile at each level (staff and the owner are handled separately in can_view).
_AUDIENCE = {
    PRIVATE: set(),
    ALUMNI_ONLY: {rbac.ALUMNI},
    INSTITUTION: {rbac.ALUMNI, rbac.STUDENT},
    PUBLIC: {rbac.ALUMNI, rbac.STUDENT, None},      # None = anonymous
}

# What a non-staff, non-owner viewer may ever receive.
SHARED_FIELDS = ("id", "name", "graduation_year", "career_status", "organisations", "profile", "timeline")
# What the owner sees about themselves: their own record, without internal reminder bookkeeping or the secret link.
OWNER_HIDDEN = {"token", "token_issued_at", "token_expires_at", "token_revoked_at", "reminders_sent", "last_reminder_at",
                "unsubscribed", "overdue", "link_status"}


def valid_level(level):
    return level in LEVELS


def get_level(c, alumni_id):
    r = c.execute("SELECT level FROM profile_visibility WHERE alumni_id=?", (alumni_id,)).fetchone()
    return r["level"] if r else DEFAULT_LEVEL


def set_level(c, alumni_id, level, updated_by):
    if not valid_level(level):
        raise ValueError("level must be one of " + ", ".join(LEVELS))
    c.execute("INSERT INTO profile_visibility(alumni_id,level,updated_at,updated_by) VALUES(?,?,?,?) "
              "ON CONFLICT(alumni_id) DO UPDATE SET level=excluded.level, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
              (alumni_id, level, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), updated_by))


def can_view(level, principal, alumni_id):
    """May `principal` (None = anonymous) see this alumnus' shared profile at `level`?"""
    if principal is not None:
        if principal.role in rbac.STAFF_ROLES:
            return True
        if principal.alumni_id is not None and principal.alumni_id == alumni_id:
            return True
    return (principal.role if principal else None) in _AUDIENCE.get(level, set())


def organisations(c, alumni_id):
    """Employer / university / startup names only. No salary, no letters, no registration numbers."""
    out = [r[0] for r in c.execute("SELECT employer FROM offers WHERE alumni_id=? AND employer IS NOT NULL ORDER BY package_lpa DESC", (alumni_id,))]
    out += [r[0] for r in c.execute("SELECT institution FROM higher_studies WHERE alumni_id=? AND institution IS NOT NULL ORDER BY id", (alumni_id,))]
    out += [r[0] for r in c.execute("SELECT company FROM ventures WHERE alumni_id=? AND company IS NOT NULL ORDER BY id", (alumni_id,))]
    seen, uniq = set(), []
    for o in out:
        if o.lower() not in seen:
            seen.add(o.lower())
            uniq.append(o)
    return uniq


def member_view(c, row):
    """The allow-listed profile other members may see. `profile` carries only profiles.MEMBER_FIELDS (never the WhatsApp
    number) plus skills and interests; `timeline` carries live events only."""
    aid = row["id"]
    p = profiles.get(c, aid)
    prof = {k: p[k] for k in profiles.MEMBER_FIELDS}
    prof["skills"], prof["interests"] = p["skills"], p["interests"]
    return {"id": aid, "name": row["name"], "graduation_year": row["graduation_year"], "career_status": row["career_status"],
            "organisations": organisations(c, aid), "profile": prof, "timeline": careers.member_view(careers.list_events(c, aid, False))}


def levels_visible_to(principal):
    role = principal.role if principal else None
    if role in rbac.STAFF_ROLES:
        return set(LEVELS)
    return {lvl for lvl, audience in _AUDIENCE.items() if role in audience}


def directory(c, principal, search="", batch=None, page=1, page_size=24):
    """Profiles this viewer may browse, in the member view (staff browsing here see exactly what a student would;
    their full tools are the Alumni directory). A person always appears to themself."""
    levels = sorted(levels_visible_to(principal))
    own = principal.alumni_id if principal and principal.alumni_id else None
    where = [f"(COALESCE(v.level,'PRIVATE') IN ({','.join('?' * len(levels))})" + (" OR a.id=?)" if own else ")")]
    args = levels + ([own] if own else [])
    if batch:
        where.append("a.graduation_year=?")
        args.append(int(batch))
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        where.append("(a.name LIKE ? OR EXISTS(SELECT 1 FROM offers o WHERE o.alumni_id=a.id AND o.employer LIKE ?) "
                     "OR EXISTS(SELECT 1 FROM higher_studies h WHERE h.alumni_id=a.id AND h.institution LIKE ?) "
                     "OR EXISTS(SELECT 1 FROM ventures vv WHERE vv.alumni_id=a.id AND vv.company LIKE ?) "
                     "OR EXISTS(SELECT 1 FROM profiles p WHERE p.alumni_id=a.id AND (p.professional_domain LIKE ? OR p.city LIKE ? OR p.country LIKE ? OR p.designation LIKE ?)) "
                     "OR EXISTS(SELECT 1 FROM profile_skills s WHERE s.alumni_id=a.id AND s.skill LIKE ?))")
        args += [like] * 9
    base = f"FROM alumni a LEFT JOIN profile_visibility v ON v.alumni_id=a.id WHERE {' AND '.join(where)}"
    total = c.execute(f"SELECT COUNT(*) n {base}", args).fetchone()["n"]
    rows = c.execute(f"SELECT a.* {base} ORDER BY a.name COLLATE NOCASE LIMIT ? OFFSET ?", args + [page_size, (max(page, 1) - 1) * page_size]).fetchall()
    return {"items": [member_view(c, r) for r in rows], "total": total, "page": page, "page_size": page_size}


def shape(c, row, principal):
    """The profile as `principal` is allowed to see it, or None if they may not see it at all (callers answer 404,
    never 403, so the existence of a private profile is not revealed)."""
    from . import services      # local import: services imports engine/notifier, which this module does not need

    aid = row["id"]
    level = get_level(c, aid)
    if not can_view(level, principal, aid):
        return None
    staff = principal is not None and principal.role in rbac.STAFF_ROLES
    owner = principal is not None and principal.alumni_id == aid
    if staff or owner:
        d = services.alumnus_dict(c, row)
        d.pop("token", None)
        if not staff:
            for k in OWNER_HIDDEN:
                d.pop(k, None)
        d["visibility"] = level
        d["viewer"] = "staff" if staff else "owner"
        d["profile"] = profiles.get(c, aid)                       # the person's own / staff view includes the WhatsApp number
        d["career_events"] = careers.list_events(c, aid)           # including retracted ones, struck through
        return d
    out = member_view(c, row)
    assert set(out) <= set(SHARED_FIELDS)
    out["viewer"] = "member" if principal else "anonymous"
    return out
