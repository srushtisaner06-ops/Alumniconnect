"""Sheet importer for the three NAAC/NBA record types. Reference formats (see `data/`):

  PLACEMENT         Table 4.6.1 Placement Record      data/reference_placement.xlsx
  HIGHER_STUDIES    Table 4.6.2 Higher Studies        data/reference_higher_studies.xlsx
  ENTREPRENEURSHIP  Table 4.6.3 Entrepreneurship      data/reference_entrepreneurship.xlsx

The category of an uploaded file is detected from its header row (or forced by the caller), and the
file is then validated against that category's columns."""
import csv
import io
import re
from datetime import date, datetime, timedelta

import openpyxl

PLACEMENT, HIGHER_STUDIES, ENTREPRENEURSHIP = "PLACEMENT", "HIGHER_STUDIES", "ENTREPRENEURSHIP"

# (key, header text as printed in the reference sheet, value required?)
COMMON = [
    ("sr_no", "Sr. No.", False),
    ("name", "Name of the Student", True),
    ("prn", "PRN No.", True),
    ("class_div", "Class and Div", True),
    ("phone", "Contact No", True),
    ("email", "Email-Id", True),
]

# (key, header, value required?, accepted alternative spellings of the header)
CATEGORIES = {
    PLACEMENT: {
        "label": "Placement", "table": "Table 4.6.1 Placement Record", "sheet": "Placement", "ay": "Placement",
        "columns": [
            ("employer", "Name of the Employer", True, []),
            ("package", "Package", True, []),
            ("position", "Position", False, []),
            ("letter_ref", "Appointment letter reference number and Date", False, []),
            ("letter_link", "Appointment letter PDF Link", False, []),
        ],
        "sample": ["Company", 8.5, "Software Engineer", "", ""],
    },
    HIGHER_STUDIES: {
        "label": "Higher Studies", "table": "Table 4.6.2 Higher Studies", "sheet": "Higher Studies", "ay": "Higher Studies",
        "columns": [
            # The reference sheet spells it "Higer"; the correct spelling is accepted too.
            ("degree", "Higer Education Degree Name", True, ["Higher Education Degree Name"]),
            ("institution", "College/University Address", True, ["College/University Name", "College / University Address"]),
            ("letter_link", "Appointment letter PDF Link", False, ["Admission letter PDF Link"]),
        ],
        "sample": ["MS in Computer Science", "University of Example, City, Country", ""],
    },
    ENTREPRENEURSHIP: {
        "label": "Entrepreneurship", "table": "Table 4.6.3 Entrepreneurship", "sheet": "Entrepreneurship", "ay": "Entrepreneurship",
        "columns": [
            ("company", "Name of the Company", True, []),
            ("reg_no", "Registration No.", True, ["Registration Number"]),
            ("website", "Official Website", False, []),
            ("letter_link", "Registration letter PDF Link", False, []),
        ],
        "sample": ["Startup Pvt. Ltd.", "U00000PN2024PTC000000", "https://example.com", ""],
    },
}
CATEGORY_ORDER = [PLACEMENT, HIGHER_STUDIES, ENTREPRENEURSHIP]

# Back-compat: the placement format as (key, header, required) triples.
COLUMNS = COMMON + [(k, h, r) for k, h, r, _ in CATEGORIES[PLACEMENT]["columns"]]


def norm(h):
    return re.sub(r"[^a-z0-9]+", "", str(h or "").lower())


def columns(category):
    """[(key, header, required)] for a category, common columns first."""
    return COMMON + [(k, h, r) for k, h, r, _ in CATEGORIES[category]["columns"]]


def headers(category):
    return [h for _, h, _ in columns(category)]


def formats():
    """Describes every supported format (used by the Import page)."""
    return [{"category": c, "label": CATEGORIES[c]["label"], "table": CATEGORIES[c]["table"], "columns": headers(c)}
            for c in CATEGORY_ORDER]


# Optional extra column: lets you pre-fill the Telegram chat id of test contacts.
OPTIONAL_COLUMNS = [("telegram_chat_id", "Telegram Chat ID")]
_COMMON_LOOKUP = {norm(h): k for k, h, _ in COMMON}


def _lookup(category):
    m = dict(_COMMON_LOOKUP)
    for k, h, _, aliases in CATEGORIES[category]["columns"]:
        m[norm(h)] = k
        for a in aliases:
            m[norm(a)] = k
    m.update({norm(h): k for k, h in OPTIONAL_COLUMNS})
    return m


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AY_RE = re.compile(r"AY\s*:?\s*(\d{4})\s*[-–/]\s*(\d{2,4})", re.I)
# VIT PRNs are 8 digits (e.g. 12210667); 12-digit PRNs are accepted as well.
PRN_RE = re.compile(r"\d{8}|\d{12}")
PRN_HINT = "8 or 12 digits"


class FormatError(Exception):
    pass


def _cell_rows(filename, content):
    """Yield (sheet_name, [list of rows as tuples])."""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        yield "CSV", [tuple(r) for r in csv.reader(io.StringIO(text))]
    elif name.endswith((".xlsx", ".xlsm")):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        except Exception as e:  # corrupt / not a real xlsx
            raise FormatError(f"Cannot open the Excel file: {e}")
        for ws in wb.worksheets:
            yield ws.title, [tuple(r) for r in ws.iter_rows(values_only=True)]
    else:
        raise FormatError("Unsupported file type. Upload .xlsx or .csv in one of the reference formats.")


def _find_header(rows):
    for i, r in enumerate(rows[:25]):
        keys = {_COMMON_LOOKUP.get(norm(c)) for c in r if c is not None}
        keys.discard(None)
        if "prn" in keys and "name" in keys:
            return i
    return None


def detect_category(header_row):
    """Pick the category whose own columns appear most in the header row (None if none do)."""
    cells = {norm(c) for c in header_row if c is not None and str(c).strip()}
    best, best_score = None, 0
    for cat in CATEGORY_ORDER:
        score = 0
        for k, h, _, aliases in CATEGORIES[cat]["columns"]:
            if k == "letter_link":      # same idea in every format, so it cannot tell them apart
                continue
            if cells & ({norm(h)} | {norm(a) for a in aliases}):
                score += 1
        if score > best_score:
            best, best_score = cat, score
    return best


def _clean_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def _prn(v):
    raw = _clean_text(v)
    digits = re.sub(r"\D", "", raw)
    return digits, (raw != digits)


def _phone(v):
    digits = re.sub(r"\D", "", _clean_text(v))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits


def _date(v):
    """Return (iso_or_none, original_text)."""
    if v is None or v == "":
        return None, ""
    if isinstance(v, datetime):
        return v.date().isoformat(), ""
    if isinstance(v, date):
        return v.isoformat(), ""
    if isinstance(v, (int, float)) and 30000 < v < 80000:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date().isoformat(), ""
    text = _clean_text(v)
    text = re.sub(r"\bSept\b", "Sep", text)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat(), ""
        except ValueError:
            pass
    return None, text


def _web_url(text):
    """Return a safe http(s) URL, adding https:// to a bare domain; '' when it is not a web address."""
    t = (text or "").strip()
    if not t:
        return ""
    if re.match(r"(?i)^https?://\S+$", t):
        return t
    if re.match(r"(?i)^(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", t):
        return "https://" + t
    return ""


def parse(filename, content, graduation_year=None, category=None):
    """Validate + parse. Never raises for data problems; returns a report dict
    with `students` (valid, grouped by PRN). `category` forces a format; otherwise it is detected."""
    report = {"ok": False, "sheet": None, "header_row": None, "graduation_year": graduation_year,
              "category": category, "category_label": CATEGORIES[category]["label"] if category in CATEGORIES else None,
              "detected": False, "expected_columns": [], "missing_columns": [], "extra_columns": [],
              "errors": [], "warnings": [], "total_rows": 0, "valid_rows": 0, "students": [],
              "final_year_students": None, "preview": []}
    if category is not None and category not in CATEGORIES:
        report["errors"].append({"row": None, "column": None, "message": f"Unknown category '{category}'"})
        return report
    try:
        sheets = list(_cell_rows(filename, content))
    except FormatError as e:
        report["errors"].append({"row": None, "column": None, "message": str(e)})
        return report

    chosen = None
    for sname, rows in sheets:
        h = _find_header(rows)
        if h is not None:
            chosen = (sname, rows, h)
            break
    if not chosen:
        report["expected_columns"] = headers(category or PLACEMENT)
        report["errors"].append({"row": None, "column": None, "message":
            "Header row not found. The file must have the reference columns: " + " | ".join(report["expected_columns"])})
        report["missing_columns"] = report["expected_columns"]
        return report

    sname, rows, hidx = chosen
    report["sheet"], report["header_row"] = sname, hidx + 1

    if category is None:
        category = detect_category(rows[hidx])
        report["detected"] = True
        if category is None:
            note = "Category columns (employer / degree / company)"
            report["expected_columns"] = [h for _, h, _ in COMMON] + [note]
            report["missing_columns"] = [note]
            report["errors"].append({"row": hidx + 1, "column": None, "message":
                "Could not tell which record type this is. Placement needs 'Name of the Employer' and 'Package'; "
                "Higher Studies needs 'Higer Education Degree Name' and 'College/University Address'; "
                "Entrepreneurship needs 'Name of the Company' and 'Registration No.'."})
            return report
        report["category"], report["category_label"] = category, CATEGORIES[category]["label"]
    spec = CATEGORIES[category]
    cols = columns(category)
    hdr = {k: h for k, h, _ in cols}
    hdr["telegram_chat_id"] = "Telegram Chat ID"
    report["expected_columns"] = [h for _, h, _ in cols]
    lookup = _lookup(category)

    colmap, extra = {}, []
    for ci, c in enumerate(rows[hidx]):
        if c is None or str(c).strip() == "":
            continue
        k = lookup.get(norm(c))
        if k and k not in colmap:
            colmap[k] = ci
        else:
            extra.append(str(c).strip())
    report["missing_columns"] = [h for k, h, _ in cols if k not in colmap]
    report["extra_columns"] = extra
    if report["missing_columns"]:
        report["errors"].append({"row": hidx + 1, "column": None, "message":
            f"Missing required column(s) for {spec['label']}: " + ", ".join(report["missing_columns"])})
        return report
    if extra:
        report["warnings"].append({"row": hidx + 1, "column": None,
                                   "message": "Extra column(s) ignored: " + ", ".join(extra)})

    # graduation year from "AY: 2025-26"
    if not graduation_year:
        for r in rows[:30]:
            for c in r:
                m = AY_RE.search(str(c)) if c else None
                if m:
                    y2 = m.group(2)
                    graduation_year = int(y2) if len(y2) == 4 else int(m.group(1)[:2] + y2)
                    break
            if graduation_year:
                break
    if not graduation_year:
        report["errors"].append({"row": None, "column": None, "message":
            "Graduation year not found. Add an 'AY: 2025-26' line like the reference sheet, or enter the year manually."})
        return report
    report["graduation_year"] = graduation_year

    # "Summary" sheet -> total final-year students (denominator for placement index)
    for sn, srows in sheets:
        if sn.strip().lower() == "summary":
            for r in srows:
                if r and len(r) > 1 and r[1] and "total no. of final year" in str(r[1]).lower():
                    nums = [x for x in r[2:] if isinstance(x, (int, float))]
                    if nums:
                        report["final_year_students"] = int(nums[-1])

    def cell(r, k):
        i = colmap[k]
        return r[i] if i < len(r) else None

    required_specific = [k for k, _, req, _ in spec["columns"] if req]
    students = {}
    for ridx in range(hidx + 1, len(rows)):
        r = rows[ridx]
        xl = ridx + 1
        vals = {k: cell(r, k) for k, _, _ in cols}
        vals["telegram_chat_id"] = cell(r, "telegram_chat_id") if "telegram_chat_id" in colmap else None
        if not any(_clean_text(vals[k]) for k in ("name", "prn", "email", "phone", *required_specific)):
            continue  # blank / label row (e.g. "AY: 2025-26")
        report["total_rows"] += 1
        errs = []

        def err(col, msg):
            errs.append({"row": xl, "column": col, "message": msg})

        def warn(col, msg):
            report["warnings"].append({"row": xl, "column": col, "message": msg})

        name = _clean_text(vals["name"])
        if not name:
            err(hdr["name"], "Name is empty")
        prn, cleaned = _prn(vals["prn"])
        if not PRN_RE.fullmatch(prn):
            err(hdr["prn"], f"PRN must be {PRN_HINT}, got '{_clean_text(vals['prn'])}'")
        elif cleaned:
            warn(hdr["prn"], f"PRN '{_clean_text(vals['prn'])}' cleaned to {prn}")
        phone = _phone(vals["phone"])
        if not re.fullmatch(r"[6-9]\d{9}", phone):
            err(hdr["phone"], f"Invalid 10-digit mobile number '{_clean_text(vals['phone'])}'")
        email = _clean_text(vals["email"]).lower()
        if not EMAIL_RE.match(email):
            err(hdr["email"], f"Invalid email '{_clean_text(vals['email'])}'")
        class_div = _clean_text(vals["class_div"])
        if not class_div:
            err(hdr["class_div"], "Class is empty")

        tg = _clean_text(vals["telegram_chat_id"])
        if tg and not re.fullmatch(r"-?\d{5,20}", tg):
            warn("Telegram Chat ID", f"Telegram Chat ID '{tg}' is not a number; ignored")
            tg = ""

        record = None   # the category-specific record built from this row
        if category == PLACEMENT:
            employer = _clean_text(vals["employer"])
            if not employer:
                err(hdr["employer"], "Employer is empty")
            pkg = vals["package"]
            try:
                pkg = float(str(pkg).replace(",", "").strip())
                if pkg < 0:
                    raise ValueError
                if pkg > 200:
                    warn(hdr["package"], f"Package {pkg} LPA looks unusually high")
            except (ValueError, TypeError):
                err(hdr["package"], f"Package must be a number (LPA), got '{_clean_text(vals['package'])}'")
                pkg = None
            iso, rawdate = _date(vals["letter_ref"])
            ref = iso or rawdate
            link = _clean_text(vals["letter_link"])
            if rawdate and not iso:
                warn(hdr["letter_ref"], f"Date '{rawdate}' not recognised; kept as text")
            if link and not link.lower().startswith("http"):
                ref = (ref + " | " if ref else "") + link
                link = ""
            record = {"employer": employer, "package_lpa": pkg, "position": _clean_text(vals["position"]) or None,
                      "letter_ref": ref or None, "letter_link": link or None}
        elif category == HIGHER_STUDIES:
            degree = _clean_text(vals["degree"])
            institution = _clean_text(vals["institution"])
            if not degree:
                err(hdr["degree"], "Degree name is empty")
            if not institution:
                err(hdr["institution"], "College / university is empty")
            link = _clean_text(vals["letter_link"])
            if link and not _web_url(link):
                warn(hdr["letter_link"], f"'{link}' is not a web link; ignored")
                link = ""
            record = {"degree": degree, "institution": institution, "letter_link": _web_url(link) or None}
        else:  # ENTREPRENEURSHIP
            company = _clean_text(vals["company"])
            reg_no = _clean_text(vals["reg_no"])
            if not company:
                err(hdr["company"], "Company name is empty")
            if not reg_no:
                err(hdr["reg_no"], "Registration number is empty")
            site_raw = _clean_text(vals["website"])
            site = _web_url(site_raw)
            if site_raw and not site:
                warn(hdr["website"], f"'{site_raw}' is not a web address; ignored")
            link = _clean_text(vals["letter_link"])
            if link and not _web_url(link):
                warn(hdr["letter_link"], f"'{link}' is not a web link; ignored")
                link = ""
            record = {"company": company, "registration_no": reg_no, "website": site or None,
                      "letter_link": _web_url(link) or None}

        if errs:
            report["errors"].extend(errs)
            continue
        report["valid_rows"] += 1
        s = students.get(prn)
        if s is None:
            sr = vals["sr_no"]
            s = students[prn] = {"sr_no": int(sr) if isinstance(sr, (int, float)) else None, "name": name, "prn": prn,
                                 "class_div": class_div, "phone": phone, "email": email, "category": category,
                                 "offers": [], "higher_studies": [], "ventures": [],
                                 "telegram_chat_id": tg or None}
        else:
            if s["name"].lower() != name.lower():
                warn(hdr["name"], f"PRN {prn} appears with different names ('{s['name']}' / '{name}'); first kept")
            if (s["email"], s["phone"]) != (email, phone):
                warn(None, f"PRN {prn} has different contact details in another row; first kept")
            if tg and not s.get("telegram_chat_id"):
                s["telegram_chat_id"] = tg
        bucket = {PLACEMENT: "offers", HIGHER_STUDIES: "higher_studies", ENTREPRENEURSHIP: "ventures"}[category]
        if record not in s[bucket]:
            s[bucket].append(record)

    report["students"] = list(students.values())
    bucket = {PLACEMENT: "offers", HIGHER_STUDIES: "higher_studies", ENTREPRENEURSHIP: "ventures"}[category]
    n_records = sum(len(s[bucket]) for s in report["students"])
    if report["total_rows"] == 0:
        report["errors"].append({"row": None, "column": None, "message": "No data rows found under the header"})
    multi = [s for s in report["students"] if len(s[bucket]) > 1]
    if multi:
        what = {PLACEMENT: "offers", HIGHER_STUDIES: "admissions", ENTREPRENEURSHIP: "ventures"}[category]
        report["warnings"].append({"row": None, "column": None, "message":
            f"{len(multi)} student(s) appear in more than one row (multiple {what}) and were merged by PRN"})
    report["summary"] = {"rows": report["total_rows"], "valid_rows": report["valid_rows"],
                         "unique_students": len(report["students"]), "records": n_records,
                         "offers": n_records, "error_count": len(report["errors"])}
    report["ok"] = not report["errors"]
    report["preview"] = [{"prn": s["prn"], "name": s["name"], "email": s["email"], "details": describe(s, category)}
                         for s in report["students"][:8]]
    return report


def describe(student, category):
    """One-line summary of a parsed student's records, for the import preview."""
    if category == PLACEMENT:
        return "; ".join(f"{o['employer']} ({o['package_lpa']} LPA)" for o in student["offers"])
    if category == HIGHER_STUDIES:
        return "; ".join(f"{h['degree']} — {h['institution']}" for h in student["higher_studies"])
    return "; ".join(f"{v['company']} ({v['registration_no']})" for v in student["ventures"])


def template_workbook(category=PLACEMENT):
    """Blank workbook with exactly the reference headers for a category."""
    spec = CATEGORIES[category]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = spec["sheet"]
    ws.append([spec["table"]])
    ws.append(headers(category))
    ws.append([f"AY: 2025-26 {spec['ay']}"])
    ws.append([1, "Student Full Name", 12210000, "BTech", "9999999999", "name@vit.edu"] + spec["sample"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
