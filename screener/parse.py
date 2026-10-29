"""Step 2: read the documents.

Audited accounts (text layer, read with PDFium):
  Automated, because it is robust: auditor, type of opinion, going-concern
  uncertainty, correction of errors, whether the document is a full set of
  accounts. Financial lines are kept only as CANDIDATES with file and page:
  -layout misaligns labels and values in some management-report tables, so a
  number read from the text is never final on its own.

Lighthouse sheets (pdfplumber):
  The first-page table: revenue and free float. Only
  the actual year ('A') is used; analyst estimates ('e') never feed a filter.
"""
import os
import re
from .pdf import page_texts
from .text import deaccent, es_number

AUDITORS = [
    (r"\bDELOITTE\b", "Deloitte"),
    (r"\bPRICEWATERHOUSE\w*\b|\bPWC\b", "PwC"),
    (r"\bKPMG\b", "KPMG"),
    (r"\bERNST\s*&?\s*YOUNG\b|\bEY\b(?!\w)", "EY"),     # whole word: 'EY' hides in other words
    (r"\bBDO\b", "BDO"),
    (r"\bGRANT\s+THORNTON\b", "Grant Thornton"),
    (r"\bMAZARS\b|\bFORVIS\b", "Forvis Mazars"),
    (r"\bRSM\b", "RSM"),
    (r"\bCROWE\b", "Crowe"),
    (r"\bAUREN\b", "Auren"),
    (r"\bMOORE\b", "Moore"),
    (r"\bBAKER\s+TILLY\b", "Baker Tilly"),
    (r"\bGPM\s+AUDITORS?\b", "GPM Auditors"),
    (r"\bAUDALIA\b", "Audalia"),
    (r"\bADDVANTE\b", "Addvante"),
    (r"\bUHY\b", "UHY"),
    (r"\bNEXIA\b", "Nexia"),
    (r"\bPKF\b", "PKF"),
    (r"\bBUSINESS\s+AUDIT\b", "Business Audit"),
    (r"\bAUDIAXIS\b", "Audiaxis"),
    (r"\bATTEST\b", "Attest"),
]

# Labels as they appear under the Spanish GAAP (PGC)
LINES = {
    "revenue": r"importe\s+neto\s+de\s+la\s+cifra\s+de\s+negocio",
}
NUM = re.compile(r"\(?-?\d{1,3}(?:\.\d{3})+(?:,\d+)?\)?|\(?-?\d+,\d+\)?")


def pdf_text(pdf, txt):
    """Text layer of the PDF, pages separated by form feeds, cached in txt."""
    if not (os.path.exists(txt) and os.path.getsize(txt) > 500):
        os.makedirs(os.path.dirname(txt), exist_ok=True)
        try:
            pages = page_texts(pdf)
        except Exception:                     # damaged or encrypted PDF
            return None
        with open(txt, "w", encoding="utf-8") as f:
            f.write("\f".join(pages))
    raw = open(txt, encoding="utf-8", errors="replace").read()
    return deaccent("".join(c if ord(c) < 0x2500 else " " for c in raw))


def _candidates(pages, pattern, k=4):
    out = []
    for pno, page in enumerate(pages, 1):
        for m in re.finditer(pattern, page, re.I):
            end = page.find("\n", m.end())
            tail = page[m.end():end if end > 0 else len(page)]
            vals = [v for v in (es_number(x) for x in NUM.findall(tail))
                    if v is not None and abs(v) >= 1000]
            if vals:
                out.append({"page": pno, "line": " ".join(tail.split())[:120], "vals": vals[:3]})
            if len(out) >= k:
                return out
    return out


def _units(text):
    head = text[:40000].lower()
    if re.search(r"miles\s+de\s+euros", head):
        return 1000
    if re.search(r"millones\s+de\s+euros", head):
        return 1_000_000
    return 1


def opinion(sc):
    """Type of opinion in the text of an audit report, most severe first."""
    sc = (sc or "").lower()
    if not sc:
        return None
    if re.search(r"denegacion\s+de\s+opinion|abstencion\s+de\s+opinion", sc):
        return "DISCLAIMER"
    if re.search(r"opinion\s+(desfavorable|adversa)", sc):
        return "ADVERSE"
    if re.search(r"opinion\s+con\s+salvedad", sc):
        return "QUALIFIED"
    if re.search(r"opinion\s+(favorable|no\s+modificada)", sc) or \
            re.search(r"expresan?,?\s+en\s+todos\s+los\s+aspectos\s+significativos", sc) or \
            re.search(r"expresan?\s+la\s+imagen\s+fiel", sc):
        return "CLEAN"
    return None


def going_concern(sc):
    """Going concern counts only as the auditor's own section heading. The
    standard responsibilities paragraph ("concluimos sobre si existe o no una
    incertidumbre material ... dudas significativas sobre la capacidad") is in
    every report and is not a finding."""
    return bool(re.search(r"incertidumbre\s+material\s+relacionada\s+con\s+la\s+empresa\s+en\s+funcionamiento",
                          (sc or "").lower()))


def auditor_firm(text):
    """The firm named most often in the document (ties: the one named first),
    not the first firm of the list named anywhere. The filing also cites
    other firms as advisers, previous auditors or in directors' CVs: Alquiber
    FY2025 names Deloitte twice (risk matrix, p109 and p114) and its auditor,
    BDO, eight times (p3 and the report's back page)."""
    up = (text or "").upper()
    hits = sorted((m.start(), lab) for pat, lab in AUDITORS for m in re.finditer(pat, up))
    if not hits:
        return None
    count, first = {}, {}
    for pos, lab in hits:
        count[lab] = count.get(lab, 0) + 1
        first.setdefault(lab, pos)
    return min(count, key=lambda lab: (-count[lab], first[lab]))


def audit_signals(text):
    """The opinion is classified only inside the audit report: 'salvedades'
    also appears in boilerplate elsewhere in the notes."""
    m = re.search(r"INFORME\s+DE\s+AUDITORIA", text, re.I)
    if m:
        sc = text[m.start():m.start() + 30000].lower()
    else:
        # The report's first page is sometimes an image, so the heading is
        # missing from the text. The report opens the document: read its start.
        sc = "\f".join(text.split("\f")[:12]).lower()
    firm = auditor_firm(text)
    op = opinion(sc)
    # The finding itself ("una incertidumbre material que PUEDE generar dudas",
    # singular) also counts wherever it is disclosed: under NIA-ES 570 the
    # auditor must then report on it.
    gc = going_concern(sc) or bool(re.search(
        r"incertidumbre\s+material\s+que\s+puede\s+generar\s+dudas\s+significativas", text, re.I))
    err = bool(re.search(r"correccion\s+de\s+errores[^.]{0,200}(ha\s+supuesto|se\s+ha\s+reexpres)",
                         text, re.I))
    return {"auditor": firm, "opinion": op, "going_concern": gc, "error_correction": err,
            "audit_report_found": bool(m)}


def parse_filing(pdf, txt):
    text = pdf_text(pdf, txt)
    if text is None:
        return {"parse": "TEXT_FAILED"}
    pages = text.split("\f")
    out = {"file": os.path.basename(pdf), "pages": len(pages), "chars": len(text),
           "pages_without_text": sum(1 for p in pages if len(p.strip()) < 200),
           "units": _units(text)}
    out.update(audit_signals(text))
    for k, pat in LINES.items():
        out[k] = _candidates(pages, pat)
    # A usable document has a P&L and enough text; otherwise it is a cover
    # note or a scan without a text layer, and the source has to be reopened.
    out["complete"] = bool(out["revenue"]) and bool(re.search(r"perdidas\s+y\s+ganancias", text, re.I)) \
        and len(text) > 30000
    return out


# ------------------------------------------------------------------ Lighthouse

def _nums(line, k=6):
    out = []
    for tok in re.findall(r"-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+|\(-?[\d.,]+\)", line):
        v = es_number(tok)
        if v is not None:
            out.append(v)
    return out[:k]


def _row(text, pattern, ratio_ok=False):
    """Find the label anywhere on the line and take the numbers AFTER it.

    Two layouts coexist: in the newer one the label opens the line; in the
    older one two PDF columns interleave and the label sits mid-line after
    figures from another table. Reading only the tail handles both.
    Ratio rows ('EBITDA / Ingresos') are skipped unless asked for.
    """
    for m in re.finditer(pattern, text, re.I):
        e = text.find("\n", m.end())
        tail = text[m.end():e if e > 0 else len(text)]
        if not ratio_ok and re.match(r"\s*[\d]?\s*/", tail):
            continue
        # Table vs prose: in a table the label is followed by figures; in the
        # narrative by words ('EL EBITDA REC. CAE UN -18,2%').
        if not re.match(r"\s*\d?\s*\(?-?\d", tail):
            continue
        v = _nums(tail)
        if v:
            return {"page": text[:m.start()].count("\f") + 1,
                    "line": " ".join((text[max(0, m.start() - 30):m.end()] + tail).split())[:150],
                    "vals": v}
    return None


def parse_lighthouse(pdf):
    import pdfplumber                         # imported here: only this step needs it
    with pdfplumber.open(pdf) as p:
        t = deaccent("\n\f".join((pg.extract_text() or "") for pg in p.pages[:2]))
    m = re.search(r"B[aa]sicos\s*\(EUR\s*Mn\)([^\n]*)", t, re.I)
    years = [y + ("e" if e else "A") for y, e in re.findall(r"(\d{4})(e?)", m.group(1))] if m else []
    rows = {
        "revenue": _row(t, r"Total\s+Ingresos"),
        "free_float": _row(t, r"Free\s*Float", ratio_ok=True),
    }

    def first(k):
        return rows[k]["vals"][0] if rows[k] else None
    return {"file": os.path.basename(pdf), "years": years,
            "actual_year": years[0] if years else None,
            "revenue_m": first("revenue"), "free_float_pct": first("free_float"),
            "rows": rows}
