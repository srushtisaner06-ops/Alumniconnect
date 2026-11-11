"""Structured profile: where someone is, what they do, what they know, and where to find them online.

Everything here is optional and can be filled by the alumnus themself or by staff. Nothing here goes on the public
alumni form (that stays as it is); data we already hold from the form fills blanks only, never overwrites a choice.

Sharing: `whatsapp` is contact data and is never shown to other members. Everything else is shown to other members
only at the viewer level the alumnus chose (see visibility.py).
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

TEXT_LIMITS = {"country": 80, "city": 80, "professional_domain": 80, "designation": 120, "headline": 160}
URL_HOSTS = {"linkedin_url": ("linkedin.com",), "github_url": ("github.com",), "portfolio_url": None}   # None = any public https site
SCALAR = ("whatsapp", "country", "city", "professional_domain", "years_experience", "designation", "headline",
          "linkedin_url", "github_url", "portfolio_url")
MEMBER_FIELDS = ("country", "city", "professional_domain", "years_experience", "designation", "headline",
                 "linkedin_url", "github_url", "portfolio_url")           # whatsapp is deliberately absent
MAX_TAGS = 30
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 +#./&'-]{0,39}$")


class ProfileError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def clean_phone(v):
    v = (v or "").strip()
    if not v:
        return None
    digits = re.sub(r"[\s().-]", "", v)
    plus = digits.startswith("+")
    digits = digits.lstrip("+")
    if not digits.isdigit():
        raise ProfileError("WhatsApp number may only contain digits, spaces and a leading +")
    if not plus and len(digits) == 10 and digits[0] in "6789":
        digits = "91" + digits                                   # a bare Indian mobile number
    if not 11 <= len(digits) <= 15:
        raise ProfileError("WhatsApp number must include the country code, for example +91 98765 43210")
    return "+" + digits


def clean_url(field, v):
    v = (v or "").strip()
    if not v:
        return None
    if "://" not in v:
        v = "https://" + v
    u = urlparse(v)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or "." not in host or u.username or u.password or len(v) > 200:
        raise ProfileError(f"{field.replace('_', ' ').capitalize()} must be a normal https:// address")
    if re.fullmatch(r"[\d.]+", host) or host in ("localhost",) or host.endswith((".local", ".internal")):
        raise ProfileError(f"{field.replace('_', ' ').capitalize()} must be a public website")
    allowed = URL_HOSTS[field]
    if allowed and not any(host == h or host.endswith("." + h) for h in allowed):
        raise ProfileError(f"{field.replace('_', ' ').capitalize()} must be a {allowed[0]} address")
    return v


def clean_tags(values, label):
    out, seen = [], set()
    for raw in values or []:
        t = re.sub(r"\s+", " ", str(raw)).strip()
        if not t:
            continue
        if not _TAG_RE.match(t):
            raise ProfileError(f"'{t[:40]}' is not a valid {label} (letters, numbers and + # . / & - only, up to 40 characters)")
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    if len(out) > MAX_TAGS:
        raise ProfileError(f"Please keep {label}s to {MAX_TAGS} or fewer")
    return out


def clean(data):
    """Validate a partial update. Returns {field: cleaned value} for exactly the fields that were supplied."""
    out = {}
    for k, limit in TEXT_LIMITS.items():
        if k in data:
            v = re.sub(r"\s+", " ", str(data[k] or "")).strip()
            if len(v) > limit:
                raise ProfileError(f"{k.replace('_', ' ').capitalize()} must be at most {limit} characters")
            out[k] = v or None
    if "whatsapp" in data:
        out["whatsapp"] = clean_phone(data["whatsapp"])
    if "years_experience" in data:
        v = data["years_experience"]
        if v in (None, ""):
            out["years_experience"] = None
        else:
            try:
                n = float(v)
            except (TypeError, ValueError):
                raise ProfileError("Years of experience must be a number")
            if not 0 <= n <= 60:
                raise ProfileError("Years of experience must be between 0 and 60")
            out["years_experience"] = round(n, 1)
    for k in URL_HOSTS:
        if k in data:
            out[k] = clean_url(k, data[k])
    if "skills" in data:
        out["skills"] = clean_tags(data["skills"], "skill")
    if "interests" in data:
        out["interests"] = clean_tags(data["interests"], "interest")
    return out


def get(c, aid):
    r = c.execute("SELECT * FROM profiles WHERE alumni_id=?", (aid,)).fetchone()
    d = {k: (r[k] if r else None) for k in SCALAR}
    d["skills"] = [x["skill"] for x in c.execute("SELECT skill FROM profile_skills WHERE alumni_id=? ORDER BY skill COLLATE NOCASE", (aid,))]
    d["interests"] = [x["interest"] for x in c.execute("SELECT interest FROM profile_interests WHERE alumni_id=? ORDER BY interest COLLATE NOCASE", (aid,))]
    d["updated_at"] = r["updated_at"] if r else None
    return d


def save(c, aid, data, by):
    """Apply a validated partial update (see clean()). Fields not supplied are left alone."""
    fields = clean(data)
    scalars = {k: v for k, v in fields.items() if k in SCALAR}
    if scalars or "skills" in fields or "interests" in fields:
        c.execute("INSERT INTO profiles(alumni_id,updated_at,updated_by) VALUES(?,?,?) "
                  "ON CONFLICT(alumni_id) DO UPDATE SET updated_at=excluded.updated_at, updated_by=excluded.updated_by", (aid, _now(), by))
    for k, v in scalars.items():
        c.execute(f"UPDATE profiles SET {k}=? WHERE alumni_id=?", (v, aid))        # k is from the SCALAR allow-list above
    for key, table, col in (("skills", "profile_skills", "skill"), ("interests", "profile_interests", "interest")):
        if key in fields:
            c.execute(f"DELETE FROM {table} WHERE alumni_id=?", (aid,))
            for t in fields[key]:
                c.execute(f"INSERT INTO {table}(alumni_id,{col}) VALUES(?,?)", (aid, t))
    return sorted(fields)


def fill_from_submission(c, aid, career_status, details):
    """Use what the alumnus typed on the form to fill BLANK profile fields. An existing value is never overwritten."""
    d, fill = details or {}, {}
    if career_status == "EMPLOYMENT":
        fill = {"designation": d.get("designation"), "professional_domain": d.get("industry")}
    elif career_status == "HIGHER_STUDIES":
        fill = {"country": d.get("country")}
    elif career_status == "ENTREPRENEURSHIP":
        fill = {"professional_domain": d.get("business_domain")}
    cur = get(c, aid)
    todo = {k: v for k, v in fill.items() if v and not cur.get(k)}
    if todo:
        save(c, aid, todo, "form")
