"""Step 4: check the screening figures against the audited accounts.

Lighthouse is the comparable source; the accounts are the primary one.

Without figures read from the accounts (data/extracted), revenue, the figure
every filter downstream leans on, is looked up among the candidate lines
pdftotext found in the accounts (with file and page). Both fiscal years are
written out: a DISCREPANCY is often a stale sheet, not a wrong number.

With figures read from the accounts (data/extracted), two kinds are told apart:

  automatic check   `pdftotext`: the figure was read from the PDF's text layer,
                    so the number must appear in the text of the page it cites.
                    FOUND, or NOT_FOUND / NO_FILE, which send a PASS back to
                    NEEDS_DATA.
  documented read   `agent-read` / `ocr`: the figure was read on a page image
                    (scanned page, opinion printed as an image, columns the text
                    layer scrambles). It stays as versioned data with its page.
                    Each run looks for it again: first in the text layer of the
                    page (TEXT_FOUND), then by OCR of the rendered page, if
                    Tesseract is installed (OCR_FOUND / OCR_NOT_FOUND). Without
                    Tesseract it is NOT_VERIFIED_NO_OCR. None of these changes
                    a verdict: OCR differs between machines and versions, and
                    the result must not.

A PASS whose revenue is not confirmed, or that rests on a figure missing from
its page or a cited file that is not there, goes back to NEEDS_DATA.
"""
import os
import re

from . import pdf
from .parse import NUM, going_concern, opinion, pdf_text
from .text import deaccent, es_number

AUTOMATIC, DOCUMENTED = "automatic", "documented"
# Outcomes of re-reading a documented figure. Informative only: none of them
# changes a verdict (a cited file that is missing does: NO_FILE).
DOCUMENTED_STATUSES = ("TEXT_FOUND", "OCR_FOUND", "OCR_NOT_FOUND", "OCR_FAILED",
                       "NOT_VERIFIED_NO_OCR")

TOLERANCE = 0.02


def _match(target_m, candidates, units):
    for c in candidates:
        for v in c["vals"]:
            for scale in {units, 1, 1000}:
                got = abs(v) * scale / 1e6
                if target_m and abs(got - abs(target_m)) <= TOLERANCE * abs(target_m):
                    return {"value_eur_m": round(got, 2), "page": c["page"], "line": c["line"]}
    return None


_pages = {}
_ocr = {}


def _pdf_path(cache, file):
    return next((p for p in (os.path.join(cache, d, file) for d in ("filings", "holdings", "lighthouse"))
                 if os.path.exists(p)), None)


def _page_text(cache, file, page):
    if file not in _pages:
        pdf_file = _pdf_path(cache, file)
        txt = os.path.join(cache, "text", file[:-4] + ".txt")
        text = pdf_text(pdf_file, txt) if pdf_file else None
        _pages[file] = text.split("\f") if text else None
    pages = _pages[file]
    if not pages or not 1 <= page <= len(pages):
        return None
    return pages[page - 1]


def _numbers(p):
    """Spanish format (1.234.567,89), English format (1,234,567.89) and small integers."""
    return [es_number(x) for x in NUM.findall(p)] + \
        [float(x.replace(",", "")) for x in re.findall(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?", p)] + \
        [float(x) for x in re.findall(r"(?<![\d.,])\d{1,3}(?![\d.,])", p)]


def _page_numbers(cache, file, page):
    p = _page_text(cache, file, page)
    return None if p is None else _numbers(p)


def _on_page(f, text):
    """Is the figure f on this page text? Numbers within half a unit; an opinion
    or going-concern flag as the same classifier the parser uses reads it."""
    v = f["value"]
    if f["metric"] == "audit_opinion":
        return opinion(deaccent(text)) == v
    if f["metric"] == "going_concern":
        return going_concern(deaccent(text)) == bool(v)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    if any(n is not None and abs(abs(n) - abs(v)) < 0.51 for n in _numbers(text)):
        return True
    # OCR often drops, doubles or swaps thousands separators: compare the
    # digits of large amounts (six or more), with or without the cents.
    digits = re.sub(r"\D", "", text)
    cents = f"{abs(v):.2f}".replace(".", "")
    units = str(int(abs(v)))
    return len(units) >= 6 and (cents in digits or units in digits)


def _ocr_text(cache, file, page, exe, psm):
    key = (file, page, psm)
    if key not in _ocr:
        try:
            _ocr[key] = pdf.ocr_page(_pdf_path(cache, file), page, exe, psm)
        except Exception:
            _ocr[key] = None
    return _ocr[key]


def check_figure(f, cache, ocr_exe=None):
    """Status of one figure of data/extracted against the page it cites."""
    if not _pdf_path(cache, f["file"]):
        return "NO_FILE"
    if f["method"] in ("agent-read", "ocr"):
        text = _page_text(cache, f["file"], f["page"])
        if text and len(text.strip()) > 50 and _on_page(f, text):
            return "TEXT_FOUND"
        if not ocr_exe:
            return "NOT_VERIFIED_NO_OCR"
        read = False
        for psm in ("3", "6"):
            t = _ocr_text(cache, f["file"], f["page"], ocr_exe, psm)
            if t is not None:
                read = True
                if _on_page(f, t):
                    return "OCR_FOUND"
        return "OCR_NOT_FOUND" if read else "OCR_FAILED"
    if not isinstance(f["value"], (int, float)) or isinstance(f["value"], bool):
        return "TEXT_VALUE"
    nums = _page_numbers(cache, f["file"], f["page"])
    if nums is None:
        return "NO_FILE"
    found = any(n is not None and abs(abs(n) - abs(f["value"])) < 0.51 for n in nums)
    return "FOUND" if found else "NOT_FOUND"


def kind(f):
    return DOCUMENTED if f["method"] in ("agent-read", "ocr") else AUTOMATIC


def check_extracted(isin, entry, cache, ocr_exe=None):
    return [{"isin": isin, "metric": f["metric"], "year": f.get("year"), "value": f["value"],
             "scale": f.get("scale", 1), "file": f["file"], "page": f["page"],
             "method": f["method"], "check_kind": kind(f),
             "check": check_figure(f, cache, ocr_exe), "note": f.get("note")}
            for f in (entry or {}).get("figures", [])]


def verify(row, lh, filing, ex=None, entry=None, cache=None, ocr_exe=None):
    """Returns (revenue check, per-figure checks of data/extracted)."""
    out = {"isin": row["isin"], "name": row["name"], "metric": "revenue",
           "lighthouse_eur_m": lh.get("revenue_m"), "lighthouse_file": lh.get("file"),
           "lighthouse_page": (lh.get("rows", {}).get("revenue") or {}).get("page"),
           "lighthouse_year": lh.get("actual_year"),
           "accounts_file": filing.get("file"), "accounts_year": filing.get("year")}
    figure_checks = check_extracted(row["isin"], entry, cache, ocr_exe)
    if ex and ex.get("revenue_m") is not None:
        s = ex["sources"]["revenue"]
        rev = next((r["check"] for r in figure_checks
                    if r["metric"] == "revenue" and r["year"] == ex["year"]), "UNCHECKED")
        out.update(accounts_file=s["file"], accounts_year=ex["year"], accounts_page=s["page"],
                   accounts_eur_m=round(ex["revenue_m"], 3), status="EXTRACTED_" + rev)
    elif lh.get("revenue_m") is None:
        out["status"] = "NO_COMPARABLE_FIGURE"
    elif not filing.get("revenue"):
        out["status"] = "NOT_IN_ACCOUNTS_TEXT"
    else:
        hit = _match(lh["revenue_m"], filing["revenue"], filing.get("units", 1))
        if hit:
            out.update(status="CONFIRMED", accounts_eur_m=hit["value_eur_m"],
                       accounts_page=hit["page"], accounts_line=hit["line"])
        else:
            c = filing["revenue"][0]
            out.update(status="DISCREPANCY", accounts_page=c["page"], accounts_line=c["line"])
    ok = out["status"] in ("CONFIRMED", "EXTRACTED_FOUND") or (
        out["status"].startswith("EXTRACTED_") and out["status"][10:] in DOCUMENTED_STATUSES)
    bad = [r for r in figure_checks if r["check"] in ("NOT_FOUND", "NO_FILE")]
    if row["verdict"] == "PASS" and (not ok or bad):
        row["verdict"] = "NEEDS_DATA"
        row["needs_data"] = ";".join(x for x in (row["needs_data"], "verify") if x)
    return out, figure_checks
