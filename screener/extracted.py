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

Judgements (C2 outside sector 06, C6 growth plan) are a verdict an agent reached on a page,
with the reasoning written down. The verifier checks that the cited file
exists; the reasoning is for a human to read.

    [[judgement]]
    filter = "C6"                 # C2 or C6
    verdict = "PASS"              # PASS or FAIL
    text = "Plan 2026-28 targets EUR 120M revenue..."
    file = "05517_OtraInfRelev_20260430.pdf"
    page = 12
    method = "agent-read"

    holders_complete = true       # top level: every insider holding is listed

Two optional tables never decide a verdict:

    [open.C4]                     # looked, not in the documents: the filter
    text = "..."                  # stays NEEDS_DATA and todo stops asking for it
    refs = ["file.pdf#1"]

    [[caveat]]                    # a weak point worth knowing, for a human reader
    text = "Part of the growth is acquired."
    refs = ["file.pdf#9"]

Definitions (fixed with the extraction, 2026-10-28):
  revenue          Importe neto de la cifra de negocios (consolidated if the
                   group reports consolidated accounts).
  free_float_pct   Strict free float: shares not held by founders, directors,
                   managers or controlling holders. 100 minus it is an UPPER
                   bound on insider ownership: it can fail C4, never pass it.
  excluded_holding_pct
                   One holding of a founder, controlling holder or director, as
                   printed in the significant-holdings filing. One entry per
                   holder; it counts as an insider holding for C4.
  insider_holding_pct
                   One holding of a founder, director or senior manager (or
                   their vehicles), as printed in the significant-holdings
                   filing or the accounts. One entry per holder, added up for
                   C4. The sum is a LOWER bound on insider ownership: it can
                   pass C4; it fails it only with `holders_complete = true`.
  intl_revenue_pct Revenue outside Spain as a share of revenue, when the
                   document prints the share (C5). scale = "pct".
  domestic_revenue Revenue in Spain from the geographic segment note, as
                   printed. With revenue of the same year it gives the share
                   outside Spain (C5): 100 * (1 - domestic / revenue).
  audit_opinion    CLEAN / QUALIFIED / ADVERSE / DISCLAIMER, read on the page
                   of the auditor's report that carries the opinion.
  going_concern    true if the report has a material-uncertainty section on
                   going concern, false if the page shows it has none.
"""
import glob
import os
import tomllib

METRICS = {"revenue", "free_float_pct", "excluded_holding_pct", "insider_holding_pct", "intl_revenue_pct", "domestic_revenue",
           "audit_opinion", "going_concern"}
JUDGED = {"C2", "C6"}
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
                           "excluded_holding_pct", "insider_holding_pct") and "year" not in f:
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
        for j in d.get("judgement", []):
            for k in ("filter", "verdict", "text", "file", "page", "method"):
                if k not in j:
                    raise ValueError(f"{isin}: judgement without '{k}': {j}")
            if j["filter"] not in JUDGED or j["verdict"] not in ("PASS", "FAIL"):
                raise ValueError(f"{isin}: bad judgement {j['filter']} {j['verdict']}")
        out[isin] = {"name": d.get("name"), "status": d.get("status"),
                     "figures": d.get("figure", []), "file": os.path.basename(path),
                     "open": d.get("open", {}), "caveats": d.get("caveat", []),
                     "judgements": d.get("judgement", []),
                     "holders_complete": bool(d.get("holders_complete"))}
    return out


def _eur(f):
    s = f.get("scale", 1)
    return f["value"] * s if isinstance(s, (int, float)) else f["value"]


def _src(f):
    if "sources" in f:
        return f["sources"]
    return {"file": f["file"], "page": f["page"], "method": f["method"]}


# One entry per holder, added up.
SUMMED = {"excluded_holding_pct", "insider_holding_pct"}


def figures(entry):
    """Collapse one company's figures into the inputs C1-C7 need.

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
    ff = by.get("free_float_pct", {})
    if ff:
        f = ff[max(ff, key=lambda k: k or 0)]
        out["free_float_pct"] = f["value"]
        out["sources"]["free_float"] = _src(f)
    xh = by.get("excluded_holding_pct", {}).get(None)
    if xh:
        out["free_float_max_pct"] = round(100 - xh["value"], 2)
        out["sources"]["free_float_max"] = xh["sources"]
    ins = [f for f in entry["figures"] if f["metric"] in ("insider_holding_pct", "excluded_holding_pct")]
    if ins:
        out["insider_pct"] = round(sum(f["value"] for f in ins), 2)
        out["sources"]["insider"] = [_src(f) for f in ins]
    out["holders_complete"] = entry.get("holders_complete", False)
    intl = by.get("intl_revenue_pct", {})
    dom = by.get("domestic_revenue", {})
    if intl:
        f = intl[max(intl, key=lambda k: k or 0)]
        out["intl_pct"] = f["value"]
        out["sources"]["intl"] = _src(f)
    elif dom and rev:
        y = max((k for k in dom if k in rev), default=None)
        if y is not None and _eur(rev[y]) > 0:
            out["intl_pct"] = round(100 * (1 - _eur(dom[y]) / _eur(rev[y])), 1)
            out["sources"]["intl"] = [_src(dom[y]), _src(rev[y])]
    for j in entry.get("judgements", []):
        out.setdefault("judgements", {})[j["filter"]] = j
        out["sources"]["judgement_" + j["filter"]] = _src(j)
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
