"""Step 5: write the run to disk (CSV, funnel.md, report.html) and print the funnel."""
import csv
import os

from . import report_html


def _csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def funnel_lines(stages, screened, cfg):
    u = cfg["universe"]
    v = {k: [r for r in screened if r["verdict"] == k] for k in ("PASS", "NEEDS_DATA", "FAIL")}
    after = [r["name"] for r in stages["listed"] if r.get("mcap_basis") == "latest_close_after_as_of"]
    lines = [
        f"BME Growth screen | universe as of {u['as_of']} | criteria fixed {cfg['criteria']['fixed_on']}",
        "",
        f"  Listed in {u['market']:<34}{len(stages['listed']):>5}",
        f"  - SOCIMIs (property vehicles){'':<15}{-len(stages['excluded_subsector']):>5}",
        f"  = Operating companies{'':<23}{len(stages['operating']):>5}",
        f"  - Outside F1 band (EUR 10-200M){'':<13}{-len(stages['outside_band']):>5}",
        f"  = Inside the band{'':<27}{len(stages['in_band']):>5}",
        f"  - Excluded by name (see config){'':<13}{-len(stages['excluded_isin']):>5}",
        f"  = Candidates screened{'':<23}{len(stages['candidates']):>5}",
        "",
        f"  Automated filters F1-F7 (F8 is manual):",
        f"    FAIL       {len(v['FAIL']):>3}",
        f"    NEEDS_DATA {len(v['NEEDS_DATA']):>3}",
        f"    PASS       {len(v['PASS']):>3}",
    ]
    if after:
        lines += ["", f"  Note: no price history before as_of for {', '.join(after)};",
                  "        latest close used for F1 (all far outside the band)."]
    return lines


SRC_COLUMNS = ("src_revenue", "src_ebitda", "src_net_debt", "src_free_float",
               "src_revenue_history", "src_opinion")


def provenance_lines(screened, figure_checks, ocr):
    """Which figures were extracted by the code on this run and which are
    documented readings (data/extracted), and how each reading checked out."""
    auto = doc = 0
    for r in screened:
        for k in SRC_COLUMNS:
            v = r.get(k) or ""
            auto += v.count("(auto: ")
            doc += v.count("(documented: ")
    text = [f for f in figure_checks if f["check_kind"] == "automatic"]
    image = [f for f in figure_checks if f["check_kind"] == "documented"]

    def tally(rows):
        c = {}
        for f in rows:
            c[f["check"]] = c.get(f["check"], 0) + 1
        return ", ".join(f"{k} {v}" for k, v in sorted(c.items())) or "-"
    return [
        "",
        "  Where the filter inputs come from (source cells in screened.csv):",
        f"    auto: extracted by the code on this run (Lighthouse table, opinion regex) {auto:>4}",
        f"    documented: read page by page, versioned in data/extracted          {doc:>4}",
        "",
        f"  Documented readings ({len(figure_checks)}), re-checked on this run (extracted_check.csv):",
        f"    read on the text layer ({len(text)}), number searched on its page: {tally(text)}",
        f"    read on page images ({len(image)}), "
        f"{'text layer, then local OCR' if ocr else 'text layer only (no OCR)'}: {tally(image)}",
    ]


def _m(v, nd=1):
    return "-" if v in (None, "") else f"{v:,.{nd}f}"


def pass_lines(screened):
    """Each PASS with the figures that decide it and where they come from."""
    out = []
    for r in (x for x in screened if x["verdict"] == "PASS"):
        out += [f"### {r['name']} ({r['isin']}), FY{r['fiscal_year']}", "",
                f"- F1 market cap EUR {_m(r['market_cap_eur_m'])}M (BME close, snapshot)",
                f"- F2 revenue EUR {_m(r['revenue_eur_m'], 2)}M: {r['src_revenue']}",
                f"- F3 EBITDA EUR {_m(r['ebitda_eur_m'], 2)}M: {r['src_ebitda']}",
                f"- F4 revenue CAGR 3y {_m(r['revenue_cagr_3y_pct'])}%: {r['src_revenue_history']}",
                f"- F5 net debt EUR {_m(r['net_debt_eur_m'], 2)}M, {_m(r['nd_ebitda'], 2)}x EBITDA: "
                f"{r['src_net_debt']}",
                f"- F6 free float {_m(r['free_float_pct'])}%: {r['src_free_float']}",
                f"- F7 opinion {r['audit_opinion']}, going concern {r['going_concern']}: {r['src_opinion']}",
                ""]
    return out


def write(out_dir, stages, screened, checks, cfg, figure_checks=(), ocr=False, notes=(),
          docs=None, extracted=None, parsed=None):
    os.makedirs(out_dir, exist_ok=True)
    stage_rows = []
    for r in stages["listed"]:
        isin = r["isin"]
        if r in stages["excluded_subsector"]:
            stage = "excluded: SOCIMI"
        elif r in stages["outside_band"]:
            stage = "excluded: outside F1 band"
        elif any(x["isin"] == isin for x in stages["excluded_isin"]):
            stage = "excluded: " + next(x["reason"] for x in stages["excluded_isin"] if x["isin"] == isin)
        else:
            stage = "candidate"
        stage_rows.append({**r, "stage": stage})
    _csv(os.path.join(out_dir, "universe_stages.csv"), stage_rows)
    order = {"PASS": 0, "NEEDS_DATA": 1, "FAIL": 2}
    screened = sorted(screened, key=lambda r: (order[r["verdict"]], r["name"]))
    _csv(os.path.join(out_dir, "screened.csv"), screened)
    _csv(os.path.join(out_dir, "verify.csv"), checks)
    _csv(os.path.join(out_dir, "extracted_check.csv"), list(figure_checks))

    lines = (funnel_lines(stages, screened, cfg)
             + provenance_lines(screened, list(figure_checks), ocr) + list(notes))
    md = ["# Funnel", "", "```", *lines, "```", "", "## Screened candidates", "",
          "| Company | Verdict | Fails | Needs data |", "|---|---|---|---|"]
    md += [f"| {r['name']} | {r['verdict']} | {r['fails'] or '-'} | {r['needs_data'] or '-'} |"
           for r in screened]
    passes = pass_lines(screened)
    if passes:
        md += ["", "## PASS: figures and sources", ""] + passes
    with open(os.path.join(out_dir, "funnel.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    report_html.write(out_dir, stages, screened, cfg, list(figure_checks), ocr, list(notes),
                      docs, extracted, parsed, cfg["universe"]["as_of"])
    return lines
