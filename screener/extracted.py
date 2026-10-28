"""Documented readings: figures read from the documents page by page, one file
per company, versioned with the repository.

The text parser cannot read every set of accounts: scanned pages,
management-report tables whose columns drift, audit opinions printed as images.
Those figures are read page by page and written to
data/extracted/<as_of>/<ISIN>.toml, each with the file and page it comes from
and the method used to read it. Every run uses them as data and re-checks each
one on its page (verify.py): a text-layer figure must be in the text of the
page; a figure read on a page image is searched by local OCR when Tesseract is
installed, and is reported as not re-verified when it is not.

    [[figure]]
    metric = "revenue"            # see METRICS
    year = 2025                   # fiscal year
    value = 12_345.0              # as printed
    scale = 1000                  # 1 = euros, 1000 = thousands of euros; "pct" for percentages
    file = "05517_OtraInfRelev_20260430.pdf"
    page = 23                     # 1-based page of the PDF
    method = "pdftotext"          # read on the PDF's text layer (the readings of
                                  #   2026-10-28 used poppler's pdftotext; the check
                                  #   now reads the same layer with PDFium)
                                  # or "agent-read" (page image read by the agent)
                                  # or "ocr" (scanned page, tesseract text read by the agent)
    note = "Consolidated P&L, line 1"

A figure that is not in this file is not invented: the filter stays NEEDS_DATA.

Definitions (fixed with the extraction, 2026-10-28):
  revenue          Importe neto de la cifra de negocios (consolidated if the
                   group reports consolidated accounts).
  ebit             Resultado de explotacion.
  da               Amortizacion del inmovilizado, as a positive amount.
  ebitda           ebit + da. Computed, never typed in.
  gross_debt       Deudas a largo plazo + Deudas a corto plazo (PGC balance
                   sheet captions B.II and C.III, or the IFRS financial
                   liabilities, leases included), one entry per caption,
                   added up here. Conservative: it includes other financial
                   liabilities as well as bank debt.
  cash             Efectivo y otros activos liquidos equivalentes. Short-term
                   financial investments are not netted (conservative).
  net_debt         gross_debt - cash. Computed.
  free_float_pct   As defined in config/criteria.toml (changelog 2026-07-28).
  excluded_holding_pct
                   One holding that the definition leaves out of the free float
                   (founder, controlling holder, director), as printed in the
                   significant-holdings filing. One entry per holder, added up:
                   100 minus the sum is an UPPER bound on free float. It can
                   fail F6 when the bound is below the bar; it never passes it.
  audit_opinion    CLEAN / QUALIFIED / ADVERSE / DISCLAIMER, read on the page
                   of the auditor's report that carries the opinion.
  going_concern    true if the report has a material-uncertainty section on
                   going concern, false if the page shows it has none.
"""
import glob
import os
import tomllib

METRICS = {"revenue", "ebit", "da", "gross_debt", "cash", "free_float_pct",
           "excluded_holding_pct", "audit_opinion", "going_concern"}
METHODS = {"pdftotext", "agent-read", "ocr"}


def _check(isin, f):
    for k in ("metric", "value", "file", "page", "method"):
        if k not in f:
            raise ValueError(f"{isin}: figure without '{k}': {f}")
    if f["metric"] not in METRICS:
        raise ValueError(f"{isin}: unknown metric {f['metric']}")
    if f["method"] not in METHODS:
        raise ValueError(f"{isin}: unknown method {f['method']}")
    if f["metric"] not in ("audit_opinion", "going_concern", "free_float_pct",
                           "excluded_holding_pct") and "year" not in f:
        raise ValueError(f"{isin}: {f['metric']} without fiscal year")


def load(root, as_of):
    """{isin: {"name":..., "figures": [figure, ...]}} for the as_of date."""
    out = {}
    for path in sorted(glob.glob(os.path.join(root, "data", "extracted", as_of, "*.toml"))):
        with open(path, "rb") as fh:
            d = tomllib.load(fh)
        isin = d["isin"]
        for f in d.get("figure", []):
            _check(isin, f)
        out[isin] = {"name": d.get("name"), "status": d.get("status"),
                     "figures": d.get("figure", []), "file": os.path.basename(path)}
    return out


def _eur(f):
    s = f.get("scale", 1)
    return f["value"] * s if isinstance(s, (int, float)) else f["value"]


def _src(f):
    if "sources" in f:
        return f["sources"]
    return {"file": f["file"], "page": f["page"], "method": f["method"]}


# Captions read line by line and added up (long-term + short-term debt).
SUMMED = {"gross_debt", "excluded_holding_pct"}


def figures(entry):
    """Collapse one company's figures into the inputs F2-F7 need.

    Returns values in EUR millions with their sources; a missing input is
    simply absent, so the filter that needs it stays NEEDS_DATA.
    """
    if not entry:
        return {}
    by, parts = {}, {}
    for f in entry["figures"]:
        m, y = f["metric"], f.get("year")
        if m in SUMMED:
            parts.setdefault(m, {}).setdefault(y, []).append(f)
            continue
        if y in by.get(m, {}):
            raise ValueError(f"{entry['file']}: {m} {y} entered twice")
        by.setdefault(m, {})[y] = f
    for m, years in parts.items():           # one figure per year, sources kept per line
        for y, fs in years.items():
            by.setdefault(m, {})[y] = {"value": sum(_eur(f) for f in fs), "scale": 1,
                                       "sources": [_src(f) for f in fs]}
    out = {"sources": {}}

    rev = by.get("revenue", {})
    if rev:
        y = max(k for k in rev if k is not None)
        out["year"] = y
        out["revenue_m"] = _eur(rev[y]) / 1e6
        out["sources"]["revenue"] = _src(rev[y])
        out["revenue_history"] = {k: _eur(v) / 1e6 for k, v in rev.items() if k is not None}
        out["sources"]["revenue_history"] = {k: _src(v) for k, v in rev.items() if k is not None}
        ebit, da = by.get("ebit", {}).get(y), by.get("da", {}).get(y)
        if ebit and da:
            out["ebitda_m"] = (_eur(ebit) + abs(_eur(da))) / 1e6
            out["sources"]["ebitda"] = [_src(ebit), _src(da)]
        gd, cash = by.get("gross_debt", {}).get(y), by.get("cash", {}).get(y)
        if gd and cash:
            out["net_debt_m"] = (_eur(gd) - _eur(cash)) / 1e6
            out["sources"]["net_debt"] = _src(gd) + [_src(cash)]
    ff = by.get("free_float_pct", {})
    if ff:
        f = ff[max(ff, key=lambda k: k or 0)]
        out["free_float_pct"] = f["value"]
        out["sources"]["free_float"] = _src(f)
    xh = by.get("excluded_holding_pct", {}).get(None)
    if xh:
        out["free_float_max_pct"] = round(100 - xh["value"], 2)
        out["sources"]["free_float_max"] = xh["sources"]
    op = by.get("audit_opinion", {})
    if op:
        f = op[max(op, key=lambda k: k or 0)]
        out["opinion"] = f["value"]
        out["sources"]["opinion"] = _src(f)
    gc = by.get("going_concern", {})
    if gc:
        f = gc[max(gc, key=lambda k: k or 0)]
        out["going_concern"] = bool(f["value"])
        out["sources"]["going_concern"] = _src(f)
    return out
