"""The run as a self-contained HTML report (runs/<as_of>/report.html).

The page carries this run's funnel, filter matrix (C1-C7), verdicts and
figures. CSS is inline and nothing is loaded from
a CDN, so the file can be opened or hosted as it is. Every figure links to its
public PDF (BME API or Lighthouse site) at the page it was read on, and says
whether it was extracted by the code on this run (auto) or read page by page
and versioned in data/extracted (documented).

Screening only: the wording reports what the filters found, never what to buy.
"""
import datetime as dt
import os
import re
import subprocess
from html import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BME_DOCS = "https://apiweb.bolsasymercados.es/Market"
LH_DOCS = "https://institutodeanalistas.com/wp-content/uploads/"
FILTERS = ("C1", "C2", "C3", "C4", "C5", "C6", "C7")
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


# ------------------------------------------------------------------ render

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{--bg:#fff;--panel:#f5f7fa;--line:#d9e0e8;--ink:#111418;--ink-2:#2b2f36;--ink-3:#5a6170;
--acc:#2563eb;--pass:#1f7a3a;--pass-bg:#dcf3e2;--need:#a86f00;--need-bg:#fdf0d5;--fail:#b3302c;--fail-bg:#fbe0df;
--mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--sans)}
.wrap{max-width:72rem;margin:0 auto;padding:2.5rem 1rem 4rem}
@media (min-width:48rem){.wrap{padding:3rem 2rem 4rem}}
.eyebrow{font:600 .72rem var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3)}
h1{font-size:clamp(1.6rem,4vw,2.4rem);line-height:1.15;margin:.5rem 0 .8rem}
h2{font-size:1.25rem;margin:2.6rem 0 .8rem}
p.lede{color:var(--ink-2);max-width:66ch}
.warn{background:var(--need-bg);border-left:4px solid var(--need);padding:.7rem .9rem;border-radius:.3rem;max-width:66ch}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.6rem;margin:1.4rem 0}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:.5rem;padding:.7rem .9rem}
.kpi b{display:block;font:700 1.6rem var(--mono)}.kpi span{font:.7rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)}
.kpi.pass{background:var(--pass-bg)}.kpi.need{background:var(--need-bg)}.kpi.fail{background:var(--fail-bg)}
pre.funnel{background:var(--panel);border:1px solid var(--line);border-radius:.5rem;padding:1rem;overflow-x:auto;font:.82rem/1.5 var(--mono)}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{padding:.45rem .5rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
thead th{font:600 .72rem var(--mono);letter-spacing:.06em;color:var(--ink-3)}
.scroll{overflow-x:auto}
td.c{text-align:center;font:700 .8rem var(--mono)}
td.PASS{color:var(--pass)}td.FAIL{color:var(--fail);background:var(--fail-bg)}td.NEEDS_DATA{color:var(--need)}
.v{font:700 .72rem var(--mono);padding:.15rem .45rem;border-radius:999px;white-space:nowrap}
.v.PASS{background:var(--pass-bg);color:var(--pass)}.v.NEEDS_DATA{background:var(--need-bg);color:var(--need)}.v.FAIL{background:var(--fail-bg);color:var(--fail)}
.card{border:1px solid var(--line);border-left:4px solid var(--pass);border-radius:.5rem;padding:1rem 1.1rem;margin:.8rem 0}
.card h3{margin:0 0 .5rem}.card dl{display:grid;grid-template-columns:3rem minmax(0,1fr);gap:.35rem .7rem;margin:0}
.card dt{font:700 .8rem var(--mono);color:var(--acc)}.card dd{margin:0;color:var(--ink-2)}
a.src{color:var(--acc)}.src{font-size:.85em}
.tag{font:.7rem var(--mono);color:var(--ink-3)}
.me{position:absolute;top:1.4rem;right:1.4rem;display:flex;align-items:center;gap:1rem;font:700 1.35rem var(--sans)}
.me a{text-decoration:none;color:#fff;background:#0a66c2;border-radius:999px;padding:.6rem 1.2rem;font-size:1.05rem}
.wrap{position:relative}
@media (max-width:40rem){.me{position:static;margin-bottom:1.2rem;font-size:1.15rem;flex-wrap:wrap;gap:.6rem}}
@media (min-width:40rem){.wrap{padding-top:5.5rem}}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--line);color:var(--ink-3);font-size:.82rem}
"""

VLABEL = {"PASS": "PASS", "NEEDS_DATA": "NEEDS DATA", "FAIL": "FAIL"}
CELL = {"PASS": "✓", "FAIL": "✕", "NEEDS_DATA": "?"}
SRC_RE = re.compile(r"(\S+) p\.(\S+) \((auto|documented): ([^)]+)\)")


def _srcs(cell, docs):
    """'file p.N (kind: method) + ...' (screened.csv) -> links to the public PDFs."""
    if not cell:
        return "<span class=tag>no source</span>"
    out = []
    for part in str(cell).split(" + "):
        m = SRC_RE.match(part)
        if not m:
            out.append(_e(part))
            continue
        f, pg, kind, meth = m.groups()
        out.append(f"{docs.link(f, pg)} <span class=tag>{kind}, {_e(METHOD_LABEL.get(meth, meth))}</span>")
    return "; ".join(out)


def _hist(cell, docs):
    if not cell:
        return "<span class=tag>no source</span>"
    return "; ".join(f"{_e(y)}: {_srcs(c, docs)}" for y, c in
                     (x.split(": ", 1) for x in str(cell).split("; ")))


def _num_or(v, unit="", nd=1):
    v = _num(v)
    return "-" if v is None else f"{v:,.{nd}f}{unit}"


def _opinion(r, say_clean=True):
    """C7 in words: the opinion as read, and the going-concern finding."""
    op = r.get("audit_opinion")
    words = f"audit opinion {_e(op)}" if op not in (None, "", "None") else "audit opinion not read"
    if str(r.get("going_concern")) == "True":
        words += ", material uncertainty on going concern"
    elif say_clean and str(r.get("going_concern")) == "False":
        words += ", no material uncertainty on going concern"
    return words


def pass_card(r, docs):
    rows = [
        ("C1", f"Market cap EUR {_num_or(r['market_cap_eur_m'])}M, BME close of the snapshot"),
        ("C2", (f"Technology sector ({_e(r['note_C2'])})" if not r.get("judgement_C2")
                else f"{_e(r['judgement_C2'])}<br>{_srcs(r['src_judgement_C2'], docs)}")),
        ("C3", f"Revenue CAGR 3y {_num_or(r['revenue_cagr_3y_pct'], '%')}<br>"
               f"{_hist(r['src_revenue_history'], docs)}"),
        ("C4", f"Founders and management {_num_or(r['insider_pct'], '%')}<br>{_srcs(r['src_insider'], docs)}"),
        ("C5", f"Revenue outside Spain {_num_or(r['intl_revenue_pct'], '%')}<br>{_srcs(r['src_intl'], docs)}"),
        ("C6", f"{_e(r['judgement_C6'])}<br>{_srcs(r['src_judgement_C6'], docs)}"),
        ("C7", f"A{_opinion(r)[1:]}<br>{_srcs(r['src_opinion'], docs)}"),
    ]
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    return f'<article class="card" id="{_e(r["isin"])}"><h3>{_e(r["name"])}</h3><dl>{dl}</dl></article>'


def fail_reason(r, cfg):
    F = cfg["filters"]
    out = []
    for k in r["fails"].split(";"):
        if k == "C1":
            out.append(f"C1 market cap EUR {_num_or(r['market_cap_eur_m'])}M")
        elif k == "C2":
            out.append("C2 " + (_e(r["judgement_C2"]) if r.get("judgement_C2")
                                else f"not a technology company ({_e(r['note_C2'])})"))
        elif k == "C3":
            out.append(f"C3 revenue CAGR {_num_or(r['revenue_cagr_3y_pct'], '%')} &lt; {F['C3']['min_pct']:g}%")
        elif k == "C4":
            out.append("C4 founders and management " + (_e(r["note_C4"]) if r.get("note_C4")
                                                        else _num_or(r["insider_pct"], "%")))
        elif k == "C5":
            out.append(f"C5 revenue outside Spain {_num_or(r['intl_revenue_pct'], '%')}")
        elif k == "C6":
            out.append("C6 " + _e(r.get("judgement_C6") or ""))
        elif k == "C7":
            out.append("C7 " + _opinion(r, say_clean=False))
    return "; ".join(out)


def _rule(k, f):
    if k == "C1":
        return f"Market cap EUR {f['min_eur'] / 1e6:g}-{f['max_eur'] / 1e6:g}M."
    rule = f.get("rule") or ""
    if "min_pct" in f:
        rule = (rule.rstrip(".") + ". " if rule else "") + f"Bar: {f['min_pct']:g}%."
    return rule


def render(stages, screened, cfg, figure_checks, ocr, notes, docs, extracted, parsed, as_of):
    from .report import funnel_lines
    D = Docs(docs)
    F = cfg["filters"]
    order = sorted(screened, key=lambda r: (ORDER[r["verdict"]], r["name"]))
    n = {k: sum(r["verdict"] == k for r in screened) for k in ORDER}
    funnel = "\n".join(funnel_lines(stages, screened, cfg))
    frows = "".join(
        f"<tr><td class=c>{k}</td><td><b>{_e(f['label'])}</b>"
        + (f" <span class=tag>criterion {_e(f['criterion'])}</span>" if f.get("criterion") else "")
        + f"</td><td>{_e(_rule(k, f))}</td><td>{'agent' if f.get('agent') else 'code'}</td></tr>"
        for k, f in F.items())
    mrows = "".join(
        f"<tr><th scope=row>{_e(r['name'])}</th>"
        + "".join(f"<td class='c {r[k]}'>{CELL.get(r[k], '-')}</td>" for k in FILTERS)
        + f"<td><span class='v {r['verdict']}'>{VLABEL[r['verdict']]}</span></td></tr>" for r in order)
    cards = "".join(pass_card(r, D) for r in order if r["verdict"] == "PASS") or \
        "<p>No company passes every filter on this run.</p>"
    fails = "".join(f"<tr><th scope=row>{_e(r['name'])}</th><td>{fail_reason(r, cfg)}</td></tr>"
                    for r in order if r["verdict"] == "FAIL")
    needs = "".join(f"<tr><th scope=row>{_e(r['name'])}</th><td>{_e(r['needs_data'])}</td></tr>"
                    for r in order if r["verdict"] == "NEEDS_DATA") or "<tr><td>No company is waiting on data.</td></tr>"
    git = _git()
    notes_html = "".join(f"<p class=tag>{_e(x)}</p>" for x in notes if x.strip())
    heads = "".join(f"<th>{k}</th>" for k in FILTERS)
    gen = f" at commit {_e(git)}" if git else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BME Growth screen, {_e(_date(as_of))}</title><style>{CSS}</style></head>
<body><div class="wrap">
<div class="me"><span>Ignasi Garcia Martin</span><a href="https://www.linkedin.com/in/ignasi-garcia">LinkedIn</a></div>
<p class="eyebrow">bme-growth-screener · universe of {_e(_date(as_of))} · criteria of {_e(_date(cfg['criteria']['fixed_on']))}</p>
<h1>Every company on BME Growth, through a venture fund's published criteria</h1>
<p class="lede">{_e(cfg['criteria']['mandate'])}.</p>
<p class="warn">A screen on public documents, not investment advice. Listed small caps are not pre-seed startups: this is a lens on the criteria, not the fund's process.</p>
<div class="kpis"><div class="kpi"><b>{len(stages['listed'])}</b><span>listed</span></div>
<div class="kpi"><b>{len(stages['candidates'])}</b><span>screened</span></div>
<div class="kpi pass"><b>{n['PASS']}</b><span>pass</span></div>
<div class="kpi need"><b>{n['NEEDS_DATA']}</b><span>needs data</span></div>
<div class="kpi fail"><b>{n['FAIL']}</b><span>fail</span></div></div>
<h2>Funnel</h2><pre class="funnel">{_e(funnel)}</pre>
<h2>Criteria</h2><div class="scroll"><table><thead><tr><th></th><th>Filter</th><th>Rule</th><th>Read by</th></tr></thead><tbody>{frows}</tbody></table></div>
<h2>Every candidate, every filter</h2>
<p class=tag>✓ pass · ✕ fail · ? needs data. A missing figure is never a pass.</p>
<div class="scroll"><table><thead><tr><th>Company</th>{heads}<th>Verdict</th></tr></thead><tbody>{mrows}</tbody></table></div>
<h2>Pass, with every figure and its page</h2>{cards}
<h2>Fail: the filter and the figure</h2><div class="scroll"><table><tbody>{fails}</tbody></table></div>
<h2>Needs data: what is missing</h2><div class="scroll"><table><tbody>{needs}</tbody></table></div>
{notes_html}
<footer><p>Public data only: BME Growth filings and Lighthouse sheets (IEAF). A screen, not investment advice.
Generated by <code>python -m screener run --as-of {_e(as_of)}</code>{gen}.</p><!-- CV link --></footer>
</div></body></html>
"""


def write(out_dir, *args, **kw):
    html = render(*args, **kw)
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(html)
