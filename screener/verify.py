"""Step 4: check the screening figures against the audited accounts.

Lighthouse is the comparable source; the accounts are the primary one.

Without figures read from the accounts (data/extracted), revenue, the figure
every filter downstream leans on, is looked up among the candidate lines
pdftotext found in the accounts (with file and page). Both fiscal years are
written out: a DISCREPANCY is often a stale sheet, not a wrong number.

With figures read from the accounts, every one marked `pdftotext` must appear
on the page it cites; a figure read from a page image (`agent-read`) cannot be
checked against text and is reported as such.

A PASS whose revenue is not confirmed, or that rests on a figure missing from
its page, goes back to NEEDS_DATA.
"""
import os
import re

from .parse import NUM, pdf_text
from .text import es_number

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


def _page_numbers(cache, file, page):
    if file not in _pages:
        pdf = next((p for p in (os.path.join(cache, d, file) for d in ("filings", "holdings", "lighthouse"))
                    if os.path.exists(p)), "")
        txt = os.path.join(cache, "txt", file[:-4] + ".txt")
        text = pdf_text(pdf, txt) if os.path.exists(pdf) else None
        _pages[file] = text.split("\f") if text else None
    pages = _pages[file]
    if not pages or not 1 <= page <= len(pages):
        return None
    p = pages[page - 1]
    return [es_number(x) for x in NUM.findall(p)] + \
        [float(x) for x in re.findall(r"(?<![\d.,])\d{1,3}(?![\d.,])", p)]


def check_figure(f, cache):
    """FOUND / NOT_FOUND / PAGE_IMAGE / TEXT_VALUE / NO_FILE for one figure."""
    if f["method"] == "agent-read":
        return "PAGE_IMAGE"
    if not isinstance(f["value"], (int, float)) or isinstance(f["value"], bool):
        return "TEXT_VALUE"
    nums = _page_numbers(cache, f["file"], f["page"])
    if nums is None:
        return "NO_FILE"
    return "FOUND" if any(n is not None and abs(abs(n) - abs(f["value"])) < 0.51 for n in nums) \
        else "NOT_FOUND"


def check_extracted(isin, entry, cache):
    return [{"isin": isin, "metric": f["metric"], "year": f.get("year"), "value": f["value"],
             "scale": f.get("scale", 1), "file": f["file"], "page": f["page"],
             "method": f["method"], "check": check_figure(f, cache), "note": f.get("note")}
            for f in (entry or {}).get("figures", [])]


def verify(row, lh, filing, ex=None, entry=None, cache=None):
    """Returns (revenue check, per-figure checks of data/extracted)."""
    out = {"isin": row["isin"], "name": row["name"], "metric": "revenue",
           "lighthouse_eur_m": lh.get("revenue_m"), "lighthouse_file": lh.get("file"),
           "lighthouse_page": (lh.get("rows", {}).get("revenue") or {}).get("page"),
           "lighthouse_year": lh.get("actual_year"),
           "accounts_file": filing.get("file"), "accounts_year": filing.get("year")}
    figure_checks = check_extracted(row["isin"], entry, cache)
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
    ok = out["status"] in ("CONFIRMED", "EXTRACTED_FOUND", "EXTRACTED_PAGE_IMAGE")
    bad = [r for r in figure_checks if r["check"] in ("NOT_FOUND", "NO_FILE")]
    if row["verdict"] == "PASS" and (not ok or bad):
        row["verdict"] = "NEEDS_DATA"
        row["needs_data"] = ";".join(x for x in (row["needs_data"], "verify") if x)
    return out, figure_checks
