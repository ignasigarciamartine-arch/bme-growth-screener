"""The run as a self-contained HTML report (runs/<as_of>/report.html).

The page is screener/templates/report.html filled with this run's funnel,
filter matrix, verdicts and figures. CSS is inline and nothing is loaded from
a CDN, so the file can be opened or hosted as it is. Every figure links to its
public PDF (BME API or Lighthouse site) at the page it was read on, and says
whether it was extracted by the code on this run (auto) or read page by page
and versioned in data/extracted (documented).

Screening only: the wording reports what the filters found, never what to buy.
"""
import datetime as dt
import os
import re
import string
import subprocess
from html import escape

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "report.html")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BME_DOCS = "https://apiweb.bolsasymercados.es/Market"
LH_DOCS = "https://institutodeanalistas.com/wp-content/uploads/"
FILTERS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")
ORDER = {"PASS": 0, "NEEDS_DATA": 1, "FAIL": 2}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

METHOD_LABEL = {
    "pdftotext": "text layer",
    "agent-read": "read on the page image",
    "ocr": "OCR of a scanned page",
    "pdfplumber": "Lighthouse table",
    "text-layer regex": "opinion regex",
}
CHECK_LABEL = {
    "FOUND": ("re-found on its page", False),
    "TEXT_VALUE": ("re-found on its page", False),
    "TEXT_FOUND": ("re-found on the text layer", False),
    "OCR_FOUND": ("re-found by OCR", False),
    "OCR_NOT_FOUND": ("not re-found by OCR", True),
    "OCR_FAILED": ("OCR failed on this run", True),
    "NOT_VERIFIED_NO_OCR": ("not re-checked: no OCR on this machine", True),
    "NOT_FOUND": ("NOT found on its page", True),
    "NO_FILE": ("cited file missing", True),
}


# ------------------------------------------------------------------ helpers

def _e(x):
    return escape(str(x), quote=True)


def _date(s):
    """'20260428', '24/04/2025' or a date -> '28 Apr 2026'."""
    if not s:
        return ""
    if isinstance(s, dt.date):
        d = s
    elif re.fullmatch(r"\d{8}", str(s)):
        d = dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
    elif re.fullmatch(r"\d{2}/\d{2}/\d{4}", str(s)):
        d = dt.date(int(s[6:]), int(s[3:5]), int(s[:2]))
    else:
        d = dt.date.fromisoformat(str(s))
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _file_date(file):
    m = re.search(r"_(\d{8})", file or "")
    return m.group(1) if m else None


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _m(v, nd=2):
    """EUR millions with a real minus sign."""
    v = _num(v)
    if v is None:
        return "-"
    s = f"{abs(v):,.{nd}f}"
    return ("−" if v < 0 else "") + s


def _git():
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                           text=True, timeout=10)
        if h.returncode:
            return None
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return h.stdout.strip() + (" with uncommitted changes" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


# ------------------------------------------------------------ documents

class Docs:
    """Public URL and a readable label for every PDF a figure can cite."""

    KIND = {"filing": "accounts", "filing_prior": "accounts", "holdings": "holdings filing",
            "lighthouse": "Lighthouse sheet"}

    def __init__(self, docs):
        self.by_file = {}
        for d in (docs or {}).values():
            for key, kind in self.KIND.items():
                x = d.get(key) or {}
                if x.get("file") and x.get("url"):
                    url = x["url"] if x["url"].startswith("http") else BME_DOCS + x["url"]
                    self.by_file[x["file"]] = {"url": url, "kind": kind, "year": x.get("year"),
                                               "date": x.get("date")}

    def info(self, file):
        base, att = file, ""
        if "__att" in file:
            base = file.split("__att")[0] + ".pdf"
            att = file[len(base) - 4:-4].replace("__att", " / attachment ").strip(" /")
        d = self.by_file.get(base)
        if d:
            url, kind, year, date = d["url"], d["kind"], d["year"], d["date"]
        else:
            # Cross-checks cite filings outside the snapshot: same public paths.
            date, year = _file_date(base), None
            if "OtraInfRelev" in base and date:
                url, kind = f"{BME_DOCS}/MTFDocuments/OtraInfRelevante/{date[:4]}/{date[4:6]}/{base}", \
                    "filing"
            elif re.fullmatch(r"[a-z0-9]+_\d{8}(_\d+)?\.pdf", base):
                url, kind = LH_DOCS + base, "Lighthouse sheet"
            else:
                url, kind = None, "document"
        if kind == "accounts" and year:
            label = f"FY{year} accounts"
        elif kind in ("Lighthouse sheet", "holdings filing", "filing"):
            label = f"{kind} {_date(date or _file_date(base))}".strip()
        else:
            label = kind
        if att:
            label += f", embedded PDF ({att})"
        return {"url": url, "label": label, "base": base, "date": date or _file_date(base)}

    def link(self, file, page=None):
        i = self.info(file)
        pg = f", p.{page}" if page not in (None, "", "-") else ""
        text = f"{_e(i['label'])}{pg}"
        if not i["url"]:
            return f'<span class="src" title="{_e(file)}">{text}</span>'
        # #page only applies to the top-level PDF, not to an embedded one.
        anchor = f"#page={page}" if pg and i["base"] == file else ""
        return f'<a class="src" href="{_e(i["url"] + anchor)}" title="{_e(file)}">{text}</a>'


def _tag(method):
    auto = method in ("pdfplumber", "text-layer regex", "bme-api")
    label = "auto" if auto else "documented"
    how = METHOD_LABEL.get(method, method)
    return f'<span class="tag {"auto" if auto else "doc"}" title="{_e(how)}">{label}</span>'


def _check(c):
    if not c:
        return ""
    text, weak = CHECK_LABEL.get(c, (c, True))
    return f' <span class="chk{" weak" if weak else ""}">&middot; {_e(text)}</span>'


SRC_RE = re.compile(r"(?P<file>\S+?\.pdf) p\.(?P<page>\S+) \((?P<kind>auto|documented): (?P<method>[^)]+)\)")


def _src_refs(src, docs):
    """'file p.N (auto: method) + ...' (screened.csv) -> links with their tag."""
    out = []
    for m in SRC_RE.finditer(src or ""):
        out.append(f'{docs.link(m["file"], m["page"])}{_tag(m["method"])}')
    return out


# --------------------------------------------------------- per company

class Company:
    """One candidate's documented figures, indexed for links and placeholders."""

    def __init__(self, row, entry, checks):
        self.row, self.entry = row, entry or {}
        self.by = {}
        for f in self.entry.get("figures", []):
            self.by.setdefault((f["metric"], f.get("year")), []).append(f)
        self.checks = {(c["metric"], c.get("year"), c["file"], c["page"], repr(c["value"])): c["check"]
                       for c in checks if c["isin"] == row["isin"]}

    def figs(self, metric, year=None):
        if year is None:
            years = [y for (m, y) in self.by if m == metric]
            if not years:
                return []
            year = max(years, key=lambda y: y or 0)
        return self.by.get((metric, year), [])

    def check(self, f):
        return self.checks.get((f["metric"], f.get("year"), f["file"], f["page"], repr(f["value"])))

    def ref(self, f, docs):
        return f'{docs.link(f["file"], f["page"])}{_tag(f["method"])}{_check(self.check(f))}'

    def resolve(self, ref, docs):
        """'metric', 'metric:year' or 'file.pdf#page' -> plain links, one per page."""
        if ".pdf#" in ref:
            file, page = ref.split("#", 1)
            return [docs.link(file, page)]
        metric, _, year = ref.partition(":")
        fs = self.figs(metric, int(year) if year else None)
        if not fs:
            raise ValueError(f"{self.row['name']}: reference {ref!r} matches no documented figure")
        return list(dict.fromkeys(docs.link(f["file"], f["page"]) for f in fs))

    def values(self, docs, cfg, as_of):
        """Placeholders for caveat texts: this run's figures, never typed in."""
        r = self.row
        rev = {}
        for (m, y), fs in self.by.items():
            if m == "revenue" and y is not None:
                f = fs[0]
                s = f.get("scale", 1)
                rev[y] = f["value"] * (s if isinstance(s, (int, float)) else 1) / 1e6
        last = max(rev) if rev else None
        cagr_from = {y: ((rev[last] / rev[y]) ** (1 / (last - y)) - 1) * 100
                     for y in rev if last and y < last and rev[y] > 0}

        def eur(metric):
            fs = self.figs(metric, last)
            return sum(f["value"] * f.get("scale", 1) for f in fs) / 1e6 if fs else None
        ebit, da = eur("ebit"), eur("da")
        ebitda, nd = _num(r.get("ebitda_eur_m")), _num(r.get("net_debt_eur_m"))
        ff = _num(r.get("free_float_pct"))
        ff_src = self.figs("free_float_pct")
        ff_date = docs.info(ff_src[0]["file"])["date"] if ff_src else None
        ff_age = None
        if ff_date:
            d0 = dt.date.fromisoformat(_iso(ff_date))
            ff_age = (as_of.year - d0.year) * 12 + as_of.month - d0.month
        return {
            "name": r["name"], "rev": rev, "cagr_from": cagr_from,
            "cagr": _num(r.get("revenue_cagr_3y_pct")), "mcap": _num(r.get("market_cap_eur_m")),
            "revenue": _num(r.get("revenue_eur_m")), "ebitda": ebitda, "ebit": ebit, "da": da,
            "da_pct": da / ebitda * 100 if da and ebitda else None,
            "nd": nd, "nd_ebitda": _num(r.get("nd_ebitda")),
            "nd_ebit": nd / ebit if nd is not None and ebit else None,
            "ff": ff, "ff_margin": ff - cfg["filters"]["F6"]["min_pct"] if ff is not None else None,
            "ff_date": _date(ff_date) if ff_date else None, "ff_age": ff_age,
        }


def _iso(s):
    s = str(s)
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
        return f"{s[6:]}-{s[3:5]}-{s[:2]}"
    return s


# ---------------------------------------------------------------- reasons

def fail_reasons(row, docs):
    """[(filter, short text, long html)] for every failing filter."""
    out = []
    srcs = lambda key: " ".join(_src_refs(row.get(key), docs))
    if row["F2"] == "FAIL":
        out.append(("F2", f"revenue EUR {_m(row['revenue_eur_m'])}M",
                    f"FY{row.get('fiscal_year') or '?'} revenue EUR {_m(row['revenue_eur_m'])}M, "
                    f"below EUR 5M. {srcs('src_revenue')}"))
    if row["F3"] == "FAIL":
        out.append(("F3", f"EBITDA EUR {_m(row['ebitda_eur_m'])}M",
                    f"EBITDA EUR {_m(row['ebitda_eur_m'])}M, not positive. {srcs('src_ebitda')}"))
    if row["F4"] == "FAIL":
        out.append(("F4", f"revenue CAGR {_m(row['revenue_cagr_3y_pct'], 1)}%",
                    f"3-year revenue CAGR {_m(row['revenue_cagr_3y_pct'], 1)}%, no growth. "
                    f"{srcs('src_revenue_history')}"))
    if row["F5"] == "FAIL":
        out.append(("F5", f"net debt {_m(row['nd_ebitda'])}x EBITDA",
                    f"Net debt {_m(row['nd_ebitda'])}x EBITDA, above 3.5x. {srcs('src_net_debt')}"))
    if row["F6"] == "FAIL":
        v = str(row.get("free_float_pct") or "")
        short = f"free float {'&le; ' + v[8:] if v.startswith('at most') else v}%"
        long_ = (f"Holders the definition excludes leave a free float of {_e(v)}%, below 15%."
                 if v.startswith("at most") else f"Free float {_e(v)}%, below 15%.")
        out.append(("F6", short, f"{long_} {srcs('src_free_float')}"))
    if row["F7"] == "FAIL":
        op, gc = row.get("audit_opinion") or "", str(row.get("going_concern")) == "True"
        what = {"QUALIFIED": "qualified opinion", "ADVERSE": "adverse opinion",
                "DISCLAIMER": "disclaimer of opinion"}.get(op)
        bits = [b for b in (what, "material uncertainty on going concern" if gc else None) if b]
        short = " and ".join(bits) or "audit opinion"
        src = srcs("src_opinion") or docs_filing_link(row, docs)
        out.append(("F7", short, f"Audit report: {_e(short)}. {src}"))
    return out


def docs_filing_link(row, docs):
    f = docs.filing_of.get(row["isin"]) if hasattr(docs, "filing_of") else None
    return f'{docs.link(f)}{_tag("text-layer regex")}' if f else ""


def needs_reason(row, d, parsed, entry, cfg, as_of, docs, comp):
    """(short text, long html) for a NEEDS_DATA candidate, from what the run holds."""
    fl = (d or {}).get("filing") or {}
    pf = (parsed or {}).get("filing") or {}
    lh = (d or {}).get("lighthouse") or {}
    open_ = [k for k in FILTERS if row.get(k) == "NEEDS_DATA"]
    span = f"{open_[0]}&ndash;{open_[-1]}" if len(open_) > 2 else " and ".join(open_)
    expected = as_of.year - 1
    no_sheet = "no Lighthouse sheet" if lh.get("status") != "OK" else "the Lighthouse sheet is for another year"
    notes = (entry or {}).get("open", {})
    if notes:
        parts = []
        for k, n in notes.items():
            text = n["text"] if isinstance(n, dict) else str(n)
            refs = [x for r in (n.get("refs", []) if isinstance(n, dict) else []) for x in comp.resolve(r, docs)]
            parts.append(f"{_e(k)} left open: {_e(text)} " + " ".join(refs))
        return f"{', '.join(notes)} undecidable from the filings", " ".join(parts)
    if fl.get("status") != "OK":
        return ("no annual accounts in BME",
                f"No annual accounts among the company's BME Growth filings up to {_date(as_of)}; "
                f"{no_sheet}. {span} stay open.")
    link = docs.link(fl["file"])
    if fl.get("year") and fl["year"] < expected:
        return (f"no FY{expected} accounts filed",
                f"The latest annual accounts filed are FY{fl['year']} ({link}); no FY{expected} accounts "
                f"by {_date(as_of)}, and {no_sheet}. {span} stay open.")
    pages, blank = pf.get("pages"), pf.get("pages_without_text")
    nblank = len(blank) if isinstance(blank, list) else blank
    if pages and nblank and nblank > pages / 2:
        return ("accounts mostly scanned, not read yet",
                f"FY{fl.get('year')} accounts filed ({link}), but {nblank} of {pages} pages are images "
                f"with no text layer. Not read page by page yet, and {no_sheet}. {span} stay open.")
    return ("accounts filed, not read yet",
            f"FY{fl.get('year')} accounts filed ({link}). Figures from the accounts enter the filters "
            f"only once read page by page (data/extracted); this company has none yet, and {no_sheet}. "
            f"{span} stay open.")


# ----------------------------------------------------------------- sections

def _cell(state, title):
    cls = {"PASS": "pass", "FAIL": "fail", "NEEDS_DATA": "need", "N/A": "na", "MANUAL": "man"}[state]
    sym = {"PASS": "", "FAIL": "&#10005;", "NEEDS_DATA": "?", "N/A": "&ndash;", "MANUAL": "&middot;"}[state]
    label = {"PASS": "pass", "FAIL": "fail", "NEEDS_DATA": "needs data", "N/A": "not applicable",
             "MANUAL": "manual, not scored"}[state]
    t = f"{label}: {title}" if title else label
    return f'<td><span class="c {cls}" title="{_e(t)}" aria-label="{_e(label)}">{sym}</span></td>'


def _cell_title(row, k):
    if k == "F1":
        return f"market cap EUR {_m(row['market_cap_eur_m'], 1)}M"
    if k == "F2" and row.get("revenue_eur_m"):
        return f"revenue EUR {_m(row['revenue_eur_m'])}M"
    if k == "F3" and row.get("ebitda_eur_m"):
        return f"EBITDA EUR {_m(row['ebitda_eur_m'])}M"
    if k == "F4" and row.get("revenue_cagr_3y_pct"):
        return f"CAGR {_m(row['revenue_cagr_3y_pct'], 1)}%"
    if k == "F5" and row.get("nd_ebitda") not in (None, ""):
        return f"{_m(row['nd_ebitda'])}x" if _num(row.get("net_debt_eur_m")) and \
            _num(row["net_debt_eur_m"]) > 0 else "net cash"
    if k == "F6" and row.get("free_float_pct"):
        return f"free float {row['free_float_pct']}%"
    if k == "F7" and row.get("audit_opinion"):
        return f"opinion {str(row['audit_opinion']).lower()}"
    return ""


def _vclass(v):
    return {"PASS": "pass", "FAIL": "fail", "NEEDS_DATA": "need"}[v]


def pass_card(row, comp, uni_row, docs, cfg):
    y = row.get("fiscal_year")
    L = []

    def fig(fid, label, value, refs):
        items = "".join(f"<li>{r}</li>" for r in refs)
        L.append(f'<div class="fig"><div class="fk"><b>{fid}</b>{label}</div>'
                 f'<div class="fv">{value}</div><div class="fs"><ul>{items}</ul></div></div>')

    u = uni_row or {}
    try:
        shares = f"{int(float(u.get('shares_as_of'))):,}"
    except (TypeError, ValueError):
        shares = "?"
    fig("F1", "Market cap", f"EUR {_m(row['market_cap_eur_m'], 1)}M",
        [f"{shares} shares &times; EUR {_e(u.get('close', '?'))} close of {_date(u.get('close_date'))}, "
         f"BME API (snapshot universe.csv){_tag('bme-api')}"])
    fig("F2", f"Revenue FY{y}", f"EUR {_m(row['revenue_eur_m'])}M",
        [comp.ref(f, docs) for f in comp.figs("revenue", int(y))])
    ebit = comp.figs("ebit", int(y))
    da = comp.figs("da", int(y))
    fig("F3", "EBITDA (EBIT + D&amp;A)", f"EUR {_m(row['ebitda_eur_m'])}M",
        [f"EBIT: {comp.ref(f, docs)}" for f in ebit] + [f"D&amp;A: {comp.ref(f, docs)}" for f in da])
    years = sorted(k[1] for k in comp.by if k[0] == "revenue" and k[1] is not None)[-4:]
    series = []
    for yy in years:
        for f in comp.figs("revenue", yy):
            v = f["value"] * f.get("scale", 1) / 1e6
            series.append(f"FY{yy} EUR {_m(v)}M: {comp.ref(f, docs)}")
    fig("F4", f"Revenue CAGR FY{years[0]}&ndash;{years[-1]}" if years else "Revenue CAGR",
        f"{_m(row['revenue_cagr_3y_pct'], 1)}%", series)
    nd = _num(row["net_debt_eur_m"])
    ratio = "net cash" if nd is not None and nd < 0 else f"{_m(row['nd_ebitda'])}x"
    debt = [f"Debt: {comp.ref(f, docs)}" for f in comp.figs("gross_debt", int(y))]
    cash = [f"Cash: {comp.ref(f, docs)}" for f in comp.figs("cash", int(y))]
    fig("F5", "Net debt / EBITDA",
        f"{ratio}<br><small>net debt EUR {_m(nd)}M</small>", debt + cash)
    fig("F6", "Free float", f"{_e(row['free_float_pct'])}%",
        [comp.ref(f, docs) for f in comp.figs("free_float_pct")])
    op = [comp.ref(f, docs) for f in comp.figs("audit_opinion")]
    gc = [comp.ref(f, docs) for f in comp.figs("going_concern")]
    fig("F7", "Audit opinion", f"{_e(str(row['audit_opinion']).capitalize())}"
        f"<br><small>no going-concern uncertainty</small>" if str(row["going_concern"]) == "False"
        else _e(row["audit_opinion"]),
        [f"Opinion: {x}" for x in op] + [f"Going concern: {x}" for x in gc if x not in op])
    fig("F8", "Catalyst and instrument fit", "not scored", ["Manual judgement, outside this run."])
    meta = f"{_e(row['isin'])} &middot; FY{_e(y)} &middot; market cap EUR {_m(row['market_cap_eur_m'], 1)}M"
    return (f'<article class="card" id="{_e(row["isin"])}"><h3 class="cname">{_e(_title(row["name"]))}</h3>'
            f'<p class="cmeta">{meta}</p><div class="figs">{"".join(L)}</div></article>')


def _title(name):
    """'LLORENTE Y CUENCA' -> 'Llorente y Cuenca'; short acronyms (NBI, NZI) stay."""
    def word(w):
        if w == "Y":
            return "y"
        if len(w) <= 3 and w.isalpha():
            return w
        return "-".join(p.capitalize() for p in w.split("-"))
    return " ".join(word(w) for w in name.split())


# ------------------------------------------------------------------- render

def render(stages, screened, cfg, figure_checks, ocr, notes, docs, extracted, parsed, as_of):
    as_of = as_of if isinstance(as_of, dt.date) else dt.date.fromisoformat(str(as_of))
    D = Docs(docs)
    D.filing_of = {isin: (d.get("filing") or {}).get("file") for isin, d in (docs or {}).items()
                   if (d.get("filing") or {}).get("status") == "OK"}
    rows = sorted(screened, key=lambda r: (ORDER[r["verdict"]], r["name"]))
    by_v = {k: [r for r in rows if r["verdict"] == k] for k in ORDER}
    comps = {r["isin"]: Company(r, (extracted or {}).get(r["isin"]), figure_checks) for r in rows}
    uni = {r["isin"]: r for r in stages["listed"]}
    F = cfg["filters"]
    n = {k: len(v) for k, v in by_v.items()}
    fixed = _date(cfg["criteria"]["fixed_on"])

    # funnel
    total = len(stages["listed"]) or 1
    steps = [
        ("keep", f"Listed on {cfg['universe']['market']}", len(stages["listed"])),
        ("drop", "SOCIMIs (property vehicles)", -len(stages["excluded_subsector"])),
        ("keep", "Operating companies", len(stages["operating"])),
        ("drop", "Market cap outside EUR 10&ndash;200M (F1)", -len(stages["outside_band"])),
        ("drop", "Removed by name, reason written in the config", -len(stages["excluded_isin"])),
        ("keep", "Candidates screened", len(stages["candidates"])),
        ("drop", "Fail at least one filter", -n["FAIL"]),
        ("drop", "Needs data (not a pass, not a fail)", -n["NEEDS_DATA"]),
        ("keep", "Pass F1&ndash;F7", n["PASS"]),
    ]
    funnel = "".join(
        f'<li class="{c}"><span class="lab">{lab}</span><span class="bar"><i style="width:'
        f'{abs(v) / total * 100:.1f}%"></i></span><span class="n">{"&minus;" + str(-v) if v < 0 else v}</span></li>'
        for c, lab, v in steps)
    after = [r["name"] for r in stages["listed"] if r.get("mcap_basis") == "latest_close_after_as_of"]
    funnel_footnote = (f'<p class="note" style="margin-top:1rem">No close on or before {_date(as_of)} for '
                       f'{_e(", ".join(_title(a) for a in after))}: the latest close is used for F1, and '
                       f'all of them are far outside the band.</p>') if after else ""

    glance_funnel = "".join(f'<li><span>{lab}</span><span class="n">{v}</span></li>' for lab, v in (
        (f"Listed on {cfg['universe']['market']}", len(stages["listed"])),
        ("Operating companies", len(stages["operating"])),
        ("Candidates screened", len(stages["candidates"]))))
    glance_verdicts = "".join(
        f'<li><span class="v {_vclass(k)}">{lab}</span><span class="n">{n[k]}</span></li>'
        for k, lab in (("PASS", "Pass"), ("NEEDS_DATA", "Needs data"), ("FAIL", "Fail")))
    glance_pass = "Pass: " + ", ".join(f'<a href="#{_e(r["isin"])}">{_e(_title(r["name"]))}</a>'
                                       for r in by_v["PASS"]) + ". F8 is manual and not scored here."

    # criteria
    thr = {"F1": f"EUR {F['F1']['min_eur'] / 1e6:.0f}&ndash;{F['F1']['max_eur'] / 1e6:.0f}M",
           "F2": f"&ge; EUR {F['F2']['min_eur_m']:.0f}M", "F3": "positive",
           "F4": f"&gt; {F['F4']['min_pct']:.0f}% a year over {F['F4']['years']} years",
           "F5": f"&lt; {F['F5']['max_x']}x", "F6": f"&ge; {F['F6']['min_pct']:.0f}%",
           "F7": "clean, no going-concern uncertainty", "F8": "judgement, not scored by the code"}.get
    criteria = "".join(f'<li><span class="fid">{k}</span><span><b>{_e(F[k]["label"])}</b>: {thr(k)}'
                       f'<span class="why">{_e(F[k]["why"])}</span></span></li>' for k in FILTERS)

    # matrix
    reasons = {}
    for r in rows:
        if r["verdict"] == "FAIL":
            fr = fail_reasons(r, D)
            reasons[r["isin"]] = ("; ".join(f"{k} {s}" for k, s, _ in fr), fr)
        elif r["verdict"] == "NEEDS_DATA":
            reasons[r["isin"]] = needs_reason(r, (docs or {}).get(r["isin"]), (parsed or {}).get(r["isin"]),
                                              (extracted or {}).get(r["isin"]), cfg, as_of, D,
                                              comps[r["isin"]])
        else:
            reasons[r["isin"]] = ("F1&ndash;F7 pass on documented figures; F8 open", None)
    mrows = []
    for k, lab in (("PASS", "Pass"), ("NEEDS_DATA", "Needs data"), ("FAIL", "Fail")):
        if not by_v[k]:
            continue
        mrows.append(f'<tr class="grp"><th colspan="11" scope="rowgroup">{lab} ({n[k]})</th></tr>')
        for r in by_v[k]:
            cells = "".join(_cell(r[f], _cell_title(r, f)) for f in FILTERS)
            mrows.append(f'<tr><th class="co" scope="row"><a href="#{_e(r["isin"])}">{_e(_title(r["name"]))}'
                         f'</a></th>{cells}<td><span class="v {_vclass(r["verdict"])}">'
                         f'{_e(r["verdict"].replace("_", " "))}</span></td>'
                         f'<td class="why">{reasons[r["isin"]][0]}</td></tr>')
    legend = "".join(f'<li><span class="c {c}">{s}</span>{t}</li>' for c, s, t in (
        ("pass", "", "pass"), ("fail", "&#10005;", "fail"), ("need", "?", "needs data"),
        ("na", "&ndash;", "not applicable (net debt ratio with negative EBITDA)"),
        ("man", "&middot;", "manual, not scored")))

    # pass cards
    pass_cards = "".join(pass_card(r, comps[r["isin"]], uni.get(r["isin"]), D, cfg) for r in by_v["PASS"])

    # fails
    fail_list = "".join(
        f'<li id="{_e(r["isin"])}"><span class="who">{_e(_title(r["name"]))}<span class="v fail">'
        f'{_e(", ".join(k for k, _, _ in reasons[r["isin"]][1]))}</span></span><span>'
        + " ".join(long_ for _, _, long_ in reasons[r["isin"]][1]) + "</span></li>"
        for r in by_v["FAIL"])

    # caveats
    cav = []
    for r in by_v["PASS"]:
        c = comps[r["isin"]]
        vals = c.values(D, cfg, as_of)
        for item in (c.entry or {}).get("caveats", []):
            text = item["text"].format(**vals)
            refs = list(dict.fromkeys(x for ref in item.get("refs", []) for x in c.resolve(ref, D)))
            cav.append(f'<li><b>{_e(_title(r["name"]))}.</b> {_e(text)}'
                       f'<span class="refs">{" &middot; ".join(refs)}</span></li>')
    weak = [(r, f) for r in by_v["PASS"] for f in figure_checks
            if f["isin"] == r["isin"] and CHECK_LABEL.get(f["check"], ("", True))[1]]
    if weak:
        names = {"free_float_pct": "free float", "gross_debt": "debt line", "da": "D&A", "ebit": "EBIT",
                 "audit_opinion": "audit opinion", "going_concern": "going concern"}
        per = {}
        for r, f in weak:
            what = names.get(f["metric"], f["metric"].replace("_", " "))
            what += f" FY{f['year']}" if f.get("year") else ""
            what += f" (p.{f['page']}, {CHECK_LABEL.get(f['check'], (f['check'],))[0]})"
            per.setdefault(_title(r["name"]), []).append(what)
        items = "; ".join(f"{_e(k)}: {_e(', '.join(v))}" for k, v in per.items())
        cav.append(f"<li><b>Re-checks.</b> Every documented reading is looked for again on its page on each "
                   f"run. {len(weak)} reading{'s' if len(weak) > 1 else ''} behind the passes "
                   f"{'were' if len(weak) > 1 else 'was'} not found again on this run. {items}. They still "
                   f"count, with their page linked in the card; the re-check never changes a verdict.</li>")
    cav.append(f"<li><b>F8 is manual.</b> {_e(F['F8']['rule'][0].upper() + F['F8']['rule'][1:])}: "
               f"a judgement on each company's filings and plans that this run does not make. A pass "
               f"here means F1&ndash;F7 are met on documented figures, nothing more.</li>")
    needs = "".join(f'<li id="{_e(r["isin"])}"><span class="who">{_e(_title(r["name"]))}'
                    f'<span class="v need">{_e(reasons[r["isin"]][0])}</span></span>'
                    f'<span>{reasons[r["isin"]][1]}</span></li>' for r in by_v["NEEDS_DATA"])
    needs_block = ""
    if by_v["NEEDS_DATA"]:
        cav.append(f'<li><b>{n["NEEDS_DATA"]} candidates are still NEEDS_DATA.</b> They are neither passes '
                   f'nor fails: missing data is never read as favourable. Each one and why is listed '
                   f'below.</li>')
        needs_block = (f'<h3 class="sub" id="needs">Still needs data ({n["NEEDS_DATA"]})</h3>'
                       f'<ul class="reasons">{needs}</ul>')

    # method
    log = "".join(f"<li><span class=\"mono\">{_e(c['date'])}</span>, {_e(c['filter'])}: {_e(c['change'])} "
                  f"<i>{_e(c['reason'])}</i></li>" for c in cfg.get("changelog", []))
    auto = doc = 0
    for r in rows:
        for k in ("src_revenue", "src_ebitda", "src_net_debt", "src_free_float", "src_revenue_history",
                  "src_opinion"):
            v = r.get(k) or ""
            auto += v.count("(auto: ")
            doc += v.count("(documented: ")
    commit = _git()
    method = "".join([
        f"<div><h3>Criteria first</h3><p>The eight filters and their thresholds were fixed on {fixed}, "
        f"before the universe was examined, in <code>config/criteria.toml</code>. Thresholds are never "
        f"edited in place; a change is appended to the changelog with its date and reason and applies "
        f"to every company, not only to survivors.</p><ul class=\"changelog\">{log}</ul></div>",
        "<div><h3>Missing data</h3><p>A filter that cannot be evaluated is NEEDS_DATA, never PASS, and "
        "one NEEDS_DATA keeps a company out of the passes. A bound on free float built from holdings "
        "the definition excludes can fail F6 but never pass it.</p></div>",
        f"<div><h3>Where figures come from</h3><p><b>auto</b>: extracted by the code on this run "
        f"(market cap from the BME API, Lighthouse tables, the opinion regex), {auto} filter inputs. "
        f"<b>documented</b>: read page by page and versioned in <code>data/extracted/</code> with file, "
        f"page and method, {doc} inputs. Accounts come before Lighthouse sheets, and a sheet is used for "
        f"P&amp;L figures only for the same fiscal year. Each documented reading is looked for again on "
        f"its page on every run{' (text layer, then local OCR)' if ocr else ' (text layer; OCR not available on this run)'}.</p></div>",
        f"<div><h3>Reproducible</h3><p>This page is written by the pipeline itself: "
        f"<span class=\"cmd\">python -m screener run --as-of {as_of.isoformat()}</span> reads the versioned "
        f"snapshot <code>data/snapshots/{as_of.isoformat()}/</code>, downloads the public documents it lists "
        f"and gives the same verdicts on any machine. "
        f"{'Code: commit ' + _e(commit) + '.' if commit else ''}</p></div>",
    ])
    if notes:
        method += ("<div><h3>Run warnings</h3><p>" + "<br>".join(_e(x.strip()) for x in notes if x.strip())
                   + "</p></div>")

    footer = (f"<p>Screening of public filings only: annual accounts and significant-holdings filings from "
              f"the BME Growth API, and Lighthouse sheets (institutodeanalistas.com). No contact with any "
              f"company, no paid databases. Not investment advice and not a valuation.</p>"
              f"<p>Ignasi Garcia Martin &middot; universe as of {_date(as_of)} &middot; criteria fixed "
              f"{fixed}</p>")

    fill = {
        "title": f"BME Growth screen, {_date(as_of)}",
        "description": f"Screen of BME Growth against eight criteria fixed on {fixed}: "
                       f"{len(stages['listed'])} listed, {len(stages['candidates'])} screened, "
                       f"{n['PASS']} pass F1-F7.",
        "eyebrow": f"BME Growth &middot; screening run &middot; universe as of {_date(as_of)}",
        "headline": f"{len(stages['listed'])} listed companies, {len(stages['candidates'])} screened, "
                    f"{n['PASS']} pass the automated filters",
        "lede": f"Every company listed on {cfg['universe']['market']} on {_date(as_of)}, screened against "
                f"eight criteria written down on {fixed}. The frame is a mandate for "
                f"{_e(cfg['criteria']['mandate']).replace('1-10M', '1&ndash;10M')}. Seven filters "
                f"(F1&ndash;F7) are applied by the code; the eighth, catalyst and instrument fit, is a "
                f"judgement and is left open.",
        "disclaimer": "Screening output, not investment advice. A pass means the company clears F1&ndash;F7 "
                      "on figures from its filings; it says nothing about price or whether the company "
                      "needs capital.",
        "glance_funnel": glance_funnel, "glance_verdicts": glance_verdicts, "glance_pass": glance_pass,
        "funnel_note": "From the full listing to the candidates, then the verdicts of the automated filters. "
                       "Bars are proportional to the number of companies.",
        "funnel": funnel, "funnel_footnote": funnel_footnote,
        "criteria_note": f"Fixed on {fixed}. Any FAIL eliminates. Thresholds and the reason for each, as "
                         f"written in the config.",
        "criteria": criteria,
        "n_candidates": str(len(rows)),
        "matrix_note": "One row per candidate. A company stops being read at its first fail, so the inputs "
                       "after it often stay as needs data. Each cell carries its value as a tooltip; the "
                       "name links to the detail. On a narrow screen the table scrolls sideways.",
        "legend": legend,
        "matrix_head": "".join(f'<th scope="col">{k}</th>' for k in FILTERS),
        "matrix_rows": "".join(mrows),
        "n_pass": str(n["PASS"]),
        "pass_note": "The figures that decide each filter, each with the document and page it was read on. "
                     "Links open the public PDF at that page.",
        "pass_cards": pass_cards,
        "n_fail": str(n["FAIL"]),
        "fail_note": "Each with the filter it fails, the figure and where it comes from.",
        "fail_list": fail_list,
        "caveats_note": "Where the passes are thin or the figures need a second look, and what is still open.",
        "caveats": "".join(cav), "needs_block": needs_block,
        "method": method,
        "footer": footer,
    }
    with open(TEMPLATE, encoding="utf-8") as fh:
        return string.Template(fh.read()).substitute(fill)


def write(out_dir, *args, **kw):
    html = render(*args, **kw)
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    return path
