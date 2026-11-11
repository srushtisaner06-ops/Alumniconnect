"""Income ranges collected on the alumni form.

People pick a *band*, never type a number: it is easier to answer, easier to keep private, and bands are what the
reports need. Codes are stable; labels may be reworded freely. Each career type measures something different:

  EMPLOYMENT        annual package (CTC) in LPA
  HIGHER_STUDIES    annual stipend / scholarship (rupee equivalent); "None / self-funded" is a valid answer
  ENTREPRENEURSHIP  annual earnings the person draws from the venture; "Not earning yet" is a valid answer

Every type has an honest "nothing yet" or lowest band, so requiring an answer never forces anyone to invent a figure.
Income is staff-only data: it is never part of what other members can see (see visibility.SHARED_FIELDS).
"""
BANDS = {
    "EMPLOYMENT": ("Annual package (CTC)", [
        ("EMP_LT3", "Below ₹3 LPA"), ("EMP_3_5", "₹3 – 5 LPA"), ("EMP_5_8", "₹5 – 8 LPA"), ("EMP_8_12", "₹8 – 12 LPA"),
        ("EMP_12_20", "₹12 – 20 LPA"), ("EMP_20_35", "₹20 – 35 LPA"), ("EMP_GT35", "Above ₹35 LPA")]),
    "HIGHER_STUDIES": ("Annual stipend or scholarship (rupee equivalent)", [
        ("HS_NONE", "None / self-funded"), ("HS_LT1", "Below ₹1 lakh"), ("HS_1_3", "₹1 – 3 lakh"), ("HS_3_6", "₹3 – 6 lakh"),
        ("HS_6_12", "₹6 – 12 lakh"), ("HS_GT12", "Above ₹12 lakh")]),
    "ENTREPRENEURSHIP": ("Annual earnings you draw from your venture", [
        ("ENT_NONE", "Not earning yet"), ("ENT_LT3", "Below ₹3 LPA"), ("ENT_3_5", "₹3 – 5 LPA"), ("ENT_5_10", "₹5 – 10 LPA"),
        ("ENT_10_25", "₹10 – 25 LPA"), ("ENT_GT25", "Above ₹25 LPA")]),
}
_LABELS = {code: label for _, (_, bands) in BANDS.items() for code, label in bands}


def valid(category, code):
    return category in BANDS and code in {c for c, _ in BANDS[category][1]}


def label(code):
    return _LABELS.get(code)


def for_form():
    """What the public form needs to render the question for each career type."""
    return {cat: {"question": q, "options": [{"code": c, "label": l} for c, l in bands]} for cat, (q, bands) in BANDS.items()}
