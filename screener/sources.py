"""Step 1b: documents for each candidate.

Two public sources:
  * Audited annual accounts, from the BME API (document type 001).
  * Lighthouse sheets: independent coverage of BME Growth companies produced by
    the Instituto Espanol de Analistas and paid for by the market. Same table
    layout for every company, so it is the comparable source for screening.
    Every figure that decides a case is then checked against the accounts.

Only documents published on or before `as_of` are eligible.
"""
import os
import re
import subprocess
import time

import requests

from . import bme
from .text import deaccent, norm_name

LH_INDEX = "https://institutodeanalistas.com/lighthouse/informes/"
LH_ROOT = "https://institutodeanalistas.com"

# --------------------------------------------------------------- annual accounts


def _size_kb(s):
    m = re.match(r"([\d.,]+)\s*(KB|MB|GB)", (s or "").strip(), re.I)
    if not m:
        return 0
    v = float(m.group(1).replace(",", "."))
    return int(v * {"kb": 1, "mb": 1024, "gb": 1024 * 1024}[m.group(2).lower()])


def _title(rec):
    return re.sub(r"<[^>]+>", "", deaccent(rec.get("title") or "")).strip()


def filing_score(rec):
    """Pick the document that holds the full accounts, not the two-page cover
    note BME often publishes later ("Informacion sobre el informe de auditoria")."""
    t = _title(rec).lower()
    s = 0
    if re.search(r"cuentas anuales", t):                          s += 60
    if re.search(r"informacion financiera (anual )?auditada", t): s += 55
    if re.search(r"informe de auditoria", t):                     s += 35
    if re.search(r"informe (financiero|anual)", t):               s += 30
    if re.search(r"consolidad", t):                               s += 20
    if re.search(r"informacion sobre el informe|comunicacion|subsanaci|aclaraci", t): s -= 70
    if re.search(r"semestr|intermedi|\b6m\b|\b1s\b", t):              s -= 80
    if re.search(r"^estado de informacion no financiera", t):     s -= 80
    if re.search(r"re-?expres", t):                               s += 10
    kb = _size_kb(rec.get("size"))
    s += min(kb / 200.0, 45)
    if kb < 300:
        s -= 40                       # two pages are not a set of accounts
    s += (rec.get("financialInfoYear") or 0) - 2024
    return s


def select_filings(records, issuer_code, as_of):
    """Annual filings published by as_of. Latest fiscal year first, among the
    documents that look like full accounts; best score breaks the tie."""
    ymd = as_of.strftime("%Y%m%d")
    rs = [r for r in records if r.get("companyKey") == issuer_code
          and r.get("financialInfoPeriod") == "AN"
          and (r.get("date") or "99999999")[:8] <= ymd]
    if not rs:
        return {"status": "NO_DOC", "n_docs": 0}
    substantive = [r for r in rs if filing_score(r) > 0] or rs
    best = max(substantive, key=lambda r: (r.get("financialInfoYear") or 0, filing_score(r)))
    rest = sorted((r for r in rs if r is not best), key=filing_score, reverse=True)
    return {
        "status": "OK", "n_docs": len(rs), "title": _title(best),
        "year": best.get("financialInfoYear"), "date": best.get("date"),
        "size": best.get("size"), "url": best.get("url"),
        "file": os.path.basename(best.get("url") or ""),
        # integrity signal I6: restatements declared in BME's own titles
        "restatement_declared": any(re.search(r"re-?expres", _title(r), re.I) for r in rs),
        "alternatives": [_title(r)[:80] for r in rest[:3]],
    }


def select_prior(records, issuer_code, as_of, latest_year, gap=2):
    """The accounts `gap` years before the latest ones. With the comparatives
    each set carries, latest + prior give the four revenue figures F4 needs."""
    if not latest_year:
        return {"status": "NO_DOC", "n_docs": 0}
    rs = [r for r in records if (r.get("financialInfoYear") or 0) == latest_year - gap]
    return select_filings(rs, issuer_code, as_of)


def harvest_filings(candidates, as_of, log=print):
    """Returns {isin: (latest accounts, accounts two years earlier)}."""
    log(f"  filings inventory {as_of.year - 3}-{as_of.year} ...")
    recs = bme.financial_information(as_of.year - 3, as_of.year)
    log(f"  {len(recs)} filings in the API")
    out = {}
    for c in candidates:
        latest = select_filings(recs, c["issuer_code"], as_of)
        out[c["isin"]] = (latest, select_prior(recs, c["issuer_code"], as_of, latest.get("year")))
    return out


def harvest_holdings(candidates, as_of, log=print):
    """Latest 'Participaciones significativas' (type 006) published by as_of:
    holders of 5% or more and directors and managers with 1% or more. It is
    the primary source for free float (F6)."""
    out = {}
    for c in candidates:
        recs = bme.documents(c["issuer_code"], "006", as_of.strftime("%Y%m%d"))
        recs.sort(key=lambda r: (r.get("date") or "", r.get("hour") or ""), reverse=True)
        if not recs:
            out[c["isin"]] = {"status": "NO_DOC", "n_docs": 0}
        else:
            r = recs[0]
            out[c["isin"]] = {"status": "OK", "n_docs": len(recs), "title": _title(r),
                              "date": r.get("date"), "size": r.get("size"), "url": r.get("url"),
                              "file": os.path.basename(r.get("url") or "")}
        time.sleep(0.15)
    log(f"  significant-holdings filings found for "
        f"{sum(v['status'] == 'OK' for v in out.values())} of {len(out)}")
    return out


def download_filings(filings, cache_dir, offline, log=print, folder="filings"):
    d = os.path.join(cache_dir, folder)
    os.makedirs(d, exist_ok=True)
    for isin, f in filings.items():
        if f["status"] != "OK":
            continue
        dest = os.path.join(d, f["file"])
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            continue
        if offline:
            f["status"] = "NOT_IN_CACHE"
            log(f"  offline, not cached: {f['file']}")
            continue
        ok = bme.download_document(f["url"], dest)
        f["status"] = "OK" if ok else "DOWNLOAD_FAILED"
        log(f"  {'downloaded' if ok else 'FAILED    '} {f['file']}")
        time.sleep(0.15)


def _detach(d, file, depth=2):
    """Save the PDFs embedded in d/file as <file>__att<N>.pdf, recursively:
    portfolios nest (a cover holding a cover holding the accounts)."""
    try:
        out = subprocess.run(["pdfdetach", "-list", os.path.join(d, file)], capture_output=True,
                             text=True, errors="replace", timeout=60).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    saved = []
    for m in re.finditer(r"^(\d+):\s*(.+)$", out, re.M):
        n, name = int(m.group(1)), m.group(2).strip()
        if not name.lower().endswith(".pdf"):
            continue
        dest = f"{file[:-4]}__att{n}.pdf"
        if not os.path.exists(os.path.join(d, dest)):
            subprocess.run(["pdfdetach", "-save", str(n), "-o", os.path.join(d, dest),
                            os.path.join(d, file)], capture_output=True, timeout=120)
        saved.append({"file": dest, "name": name})
        if depth > 1:
            saved += _detach(d, dest, depth - 1)
    return saved


def detach_attachments(filings, cache_dir, log=print, folder="filings"):
    """Some issuers file a short cover PDF with the accounts embedded as
    attachments (PDF portfolio). Each embedded PDF is saved next to it, so it
    can be read and cited by page like any filing."""
    d = os.path.join(cache_dir, folder)
    for f in filings.values():
        if f.get("status") != "OK":
            continue
        f["attachments"] = _detach(d, f["file"])
        if f["attachments"]:
            log(f"  {f['file']}: {len(f['attachments'])} embedded PDF(s) saved")


# ------------------------------------------------------------- Lighthouse sheets

_BLOCK = re.compile(
    r"<h3>(?P<name>[^<]{2,80})</h3>\s*<p>.*?Fecha:\s*(?P<date>\d{2}/\d{2}/\d{4}).*?"
    r"PDF:\s*<a href='(?P<url>[^']+\.pdf)'", re.S | re.I)


def lighthouse_index():
    html = requests.get(LH_INDEX, headers={"User-Agent": "Mozilla/5.0"},
                        timeout=60).content.decode("utf-8", "replace")
    out = []
    for m in _BLOCK.finditer(html):
        d = m.group("date")
        url = m.group("url")
        out.append({"lh_name": deaccent(m.group("name")).strip(), "date": d,
                    "ymd": d[6:10] + d[3:5] + d[0:2],
                    "url": LH_ROOT + url if url.startswith("/") else url})
    return out


def select_lighthouse(index, name, as_of):
    ymd = as_of.strftime("%Y%m%d")
    by = {}
    for r in index:
        if r["ymd"] <= ymd:
            by.setdefault(norm_name(r["lh_name"]), []).append(r)
    k = norm_name(name)
    hit = by.get(k)
    if not hit:                       # names differ between sources: match on prefix
        for kk, v in by.items():
            if kk.startswith(k[:8]) or k.startswith(kk[:8]):
                hit = v
                break
    if not hit:
        return {"status": "NO_COVERAGE"}
    hit.sort(key=lambda r: r["ymd"], reverse=True)
    best = hit[0]
    return {"status": "OK", "lh_name": best["lh_name"], "date": best["date"],
            "url": best["url"], "file": os.path.basename(best["url"]),
            "n_reports": len(hit)}


def harvest_lighthouse(candidates, as_of, log=print):
    idx = lighthouse_index()
    log(f"  Lighthouse index: {len(idx)} sheets")
    return {c["isin"]: select_lighthouse(idx, c["name"], as_of) for c in candidates}


def download_lighthouse(sheets, cache_dir, offline, log=print):
    d = os.path.join(cache_dir, "lighthouse")
    os.makedirs(d, exist_ok=True)
    for isin, s in sheets.items():
        if s["status"] != "OK":
            continue
        dest = os.path.join(d, s["file"])
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            continue
        if offline:
            s["status"] = "NOT_IN_CACHE"
            continue
        r = requests.get(s["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            with open(dest, "wb") as f:
                f.write(r.content)
        else:
            s["status"] = "DOWNLOAD_FAILED"
        time.sleep(0.2)
