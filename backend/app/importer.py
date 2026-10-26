"""Placement-sheet importer. The reference format is `data/reference_placement.xlsx`
(Table 4.6.1 Placement Record). Any uploaded file is validated against it."""
import csv
import io
import re
from datetime import date, datetime, timedelta

import openpyxl

# key, header text in the reference sheet, value required?
COLUMNS = [
    ("sr_no", "Sr. No.", False),
    ("name", "Name of the Student", True),
    ("prn", "PRN No.", True),
    ("class_div", "Class and Div", True),
    ("phone", "Contact No", True),
    ("email", "Email-Id", True),
    ("employer", "Name of the Employer", True),
    ("package", "Package", True),
    ("position", "Position", False),
    ("letter_ref", "Appointment letter reference number and Date", False),
    ("letter_link", "Appointment letter PDF Link", False),
]


def norm(h):
    return re.sub(r"[^a-z0-9]+", "", str(h or "").lower())


# Optional extra column: lets you pre-fill the Telegram chat id of test contacts.
OPTIONAL_COLUMNS = [("telegram_chat_id", "Telegram Chat ID")]
HEADER_LOOKUP = {norm(h): k for k, h, _ in COLUMNS}
HEADER_LOOKUP.update({norm(h): k for k, h in OPTIONAL_COLUMNS})
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AY_RE = re.compile(r"AY\s*:?\s*(\d{4})\s*[-–/]\s*(\d{2,4})", re.I)


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
        raise FormatError("Unsupported file type. Upload .xlsx or .csv in the reference format.")


def _find_header(rows):
    for i, r in enumerate(rows[:25]):
        keys = {HEADER_LOOKUP.get(norm(c)) for c in r if c is not None}
        keys.discard(None)
        if "prn" in keys and "name" in keys:
            return i
    return None


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


def parse(filename, content, graduation_year=None):
    """Validate + parse. Never raises for data problems; returns a report dict
    with `students` (valid, grouped by PRN)."""
    report = {"ok": False, "sheet": None, "header_row": None, "graduation_year": graduation_year,
              "expected_columns": [h for _, h, _ in COLUMNS], "missing_columns": [], "extra_columns": [],
              "errors": [], "warnings": [], "total_rows": 0, "valid_rows": 0, "students": [],
              "final_year_students": None, "preview": []}
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
        report["errors"].append({"row": None, "column": None, "message":
            "Header row not found. The file must have the reference columns: " + " | ".join(report["expected_columns"])})
        report["missing_columns"] = report["expected_columns"]
        return report

    sname, rows, hidx = chosen
    report["sheet"], report["header_row"] = sname, hidx + 1
    colmap, extra = {}, []
    for ci, c in enumerate(rows[hidx]):
        if c is None or str(c).strip() == "":
            continue
        k = HEADER_LOOKUP.get(norm(c))
        if k and k not in colmap:
            colmap[k] = ci
        else:
            extra.append(str(c).strip())
    report["missing_columns"] = [h for k, h, _ in COLUMNS if k not in colmap]
    report["extra_columns"] = extra
    if report["missing_columns"]:
        report["errors"].append({"row": hidx + 1, "column": None, "message":
            "Missing required column(s): " + ", ".join(report["missing_columns"])})
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

    students = {}
    for ridx in range(hidx + 1, len(rows)):
        r = rows[ridx]
        xl = ridx + 1
        vals = {k: cell(r, k) for k, _, _ in COLUMNS}
        vals["telegram_chat_id"] = cell(r, "telegram_chat_id") if "telegram_chat_id" in colmap else None
        if not any(_clean_text(vals[k]) for k in ("name", "prn", "email", "employer", "phone")):
            continue  # blank / label row (e.g. "AY: 2025-26")
        report["total_rows"] += 1
        errs = []

        def err(col, msg):
            errs.append({"row": xl, "column": col, "message": msg})

        name = _clean_text(vals["name"])
        if not name:
            err("Name of the Student", "Name is empty")
        prn, cleaned = _prn(vals["prn"])
        if not re.fullmatch(r"\d{12}", prn):
            err("PRN No.", f"PRN must be 12 digits, got '{_clean_text(vals['prn'])}'")
        elif cleaned:
            report["warnings"].append({"row": xl, "column": "PRN No.", "message":
                f"PRN '{_clean_text(vals['prn'])}' cleaned to {prn}"})
        phone = _phone(vals["phone"])
        if not re.fullmatch(r"[6-9]\d{9}", phone):
            err("Contact No", f"Invalid 10-digit mobile number '{_clean_text(vals['phone'])}'")
        email = _clean_text(vals["email"]).lower()
        if not EMAIL_RE.match(email):
            err("Email-Id", f"Invalid email '{_clean_text(vals['email'])}'")
        class_div = _clean_text(vals["class_div"])
        if not class_div:
            err("Class and Div", "Class is empty")
        employer = _clean_text(vals["employer"])
        if not employer:
            err("Name of the Employer", "Employer is empty")
        pkg = vals["package"]
        try:
            pkg = float(str(pkg).replace(",", "").strip())
            if pkg < 0:
                raise ValueError
            if pkg > 200:
                report["warnings"].append({"row": xl, "column": "Package", "message": f"Package {pkg} LPA looks unusually high"})
        except (ValueError, TypeError):
            err("Package", f"Package must be a number (LPA), got '{_clean_text(vals['package'])}'")
            pkg = None

        tg = _clean_text(vals["telegram_chat_id"])
        if tg and not re.fullmatch(r"-?\d{5,20}", tg):
            report["warnings"].append({"row": xl, "column": "Telegram Chat ID",
                                       "message": f"Telegram Chat ID '{tg}' is not a number; ignored"})
            tg = ""

        iso, rawdate = _date(vals["letter_ref"])
        ref = iso or rawdate
        link = _clean_text(vals["letter_link"])
        if rawdate and not iso:
            report["warnings"].append({"row": xl, "column": "Appointment letter reference number and Date",
                                       "message": f"Date '{rawdate}' not recognised; kept as text"})
        if link and not link.lower().startswith("http"):
            ref = (ref + " | " if ref else "") + link
            link = ""

        if errs:
            report["errors"].extend(errs)
            continue
        report["valid_rows"] += 1
        offer = {"employer": employer, "package_lpa": pkg, "position": _clean_text(vals["position"]) or None,
                 "letter_ref": ref or None, "letter_link": link or None}
        s = students.get(prn)
        if s is None:
            sr = vals["sr_no"]
            students[prn] = {"sr_no": int(sr) if isinstance(sr, (int, float)) else None, "name": name, "prn": prn,
                             "class_div": class_div, "phone": phone, "email": email, "offers": [offer],
                             "telegram_chat_id": tg or None}
        else:
            if s["name"].lower() != name.lower():
                report["warnings"].append({"row": xl, "column": "Name of the Student", "message":
                    f"PRN {prn} appears with different names ('{s['name']}' / '{name}'); first kept"})
            if (s["email"], s["phone"]) != (email, phone):
                report["warnings"].append({"row": xl, "column": None, "message":
                    f"PRN {prn} has different contact details in another row; first kept"})
            if tg and not s.get("telegram_chat_id"):
                s["telegram_chat_id"] = tg
            s["offers"].append(offer)

    report["students"] = list(students.values())
    n_offers = sum(len(s["offers"]) for s in report["students"])
    if report["total_rows"] == 0:
        report["errors"].append({"row": None, "column": None, "message": "No data rows found under the header"})
    multi = [s for s in report["students"] if len(s["offers"]) > 1]
    if multi:
        report["warnings"].append({"row": None, "column": None, "message":
            f"{len(multi)} student(s) appear in more than one row (multiple offers) and were merged by PRN"})
    report["summary"] = {"rows": report["total_rows"], "valid_rows": report["valid_rows"],
                         "unique_students": len(report["students"]), "offers": n_offers,
                         "error_count": len(report["errors"])}
    report["ok"] = not report["errors"]
    report["preview"] = [{"prn": s["prn"], "name": s["name"], "email": s["email"],
                          "offers": "; ".join(f"{o['employer']} ({o['package_lpa']} LPA)" for o in s["offers"])}
                         for s in report["students"][:8]]
    return report


def template_workbook():
    """Blank workbook with exactly the reference headers."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Placement"
    ws.append(["Table 4.6.1 Placement Record"])
    ws.append([h for _, h, _ in COLUMNS])
    ws.append(["AY: 2025-26 Placement"])
    ws.append([1, "Student Full Name", 12210000, "BTech", "9999999999", "name@vit.edu", "Company", 8.5, "Software Engineer", "", ""])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
