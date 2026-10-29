"""Step 3: the funnel and the filters C1-C7 (config/criteria.toml).

Rule for every filter: if it cannot be evaluated the result is NEEDS_DATA,
never PASS. Missing data is not favourable data.
"""
PASS, FAIL, NEEDS = "PASS", "FAIL", "NEEDS_DATA"


def funnel(universe, cfg):
    """Universe -> operating -> inside the C1 band -> candidates."""
    u = cfg["universe"]
    sub = {(x["sector"], x["subsector"]): x["reason"] for x in u.get("exclude_subsector", [])}
    by_isin = {x["isin"]: x["reason"] for x in u.get("exclude_isin", [])}
    f1 = cfg["filters"]["C1"]

    stages = {"listed": universe}
    stages["excluded_subsector"] = [r for r in universe if (r["sector"], r["subsector"]) in sub]
    operating = [r for r in universe if (r["sector"], r["subsector"]) not in sub]
    stages["operating"] = operating

    def mcap(r):
        v = r.get("market_cap_eur")
        return float(v) if v not in (None, "") else None

    stages["outside_band"] = [r for r in operating
                              if mcap(r) is not None and not f1["min_eur"] <= mcap(r) <= f1["max_eur"]]
    # A company without a market cap is not dropped: C1 stays NEEDS_DATA.
    in_band = [r for r in operating if mcap(r) is None or f1["min_eur"] <= mcap(r) <= f1["max_eur"]]
    stages["in_band"] = in_band
    stages["excluded_isin"] = [dict(r, reason=by_isin[r["isin"]]) for r in in_band if r["isin"] in by_isin]
    stages["candidates"] = [r for r in in_band if r["isin"] not in by_isin]
    return stages


# Methods of the parser, run on every execution. Every other method is a
# documented reading from data/extracted (see extracted.py).
AUTOMATIC_METHODS = ("pdfplumber", "text-layer regex")


def _fmt(src):
    """'file p.N (auto: method)' or 'file p.N (documented: method)'."""
    if not src:
        return None
    if isinstance(src, list):
        return " + ".join(_fmt(x) for x in src)
    kind = "auto" if src["method"] in AUTOMATIC_METHODS else "documented"
    return f"{src['file']} p.{src['page']} ({kind}: {src['method']})"


def inputs(lh, ex):
    """Financial inputs and where each comes from.

    Figures read from the accounts (data/extracted) come first: the accounts are
    the primary source. The Lighthouse sheet fills a gap only when its actual
    year is the same fiscal year, so one company's filters never mix years.
    Free float is not a fiscal-year figure: the sheet is used as published.
    """
    ex = ex or {}
    lh_page = lambda k: {"file": lh.get("file"), "method": "pdfplumber",
                         "page": (lh.get("rows", {}).get(k) or {}).get("page")}
    year = ex.get("year")
    lh_same_year = year is None or str(lh.get("actual_year") or "").startswith(str(year))
    out, src = {}, {}
    if ex.get("revenue_m") is not None:
        out["revenue_m"], src["revenue"] = ex["revenue_m"], ex["sources"]["revenue"]
    elif lh_same_year and lh.get("revenue_m") is not None:
        out["revenue_m"], src["revenue"] = lh["revenue_m"], lh_page("revenue")
    else:
        out["revenue_m"] = None
    if ex.get("free_float_pct") is not None:
        out["free_float_pct"], src["free_float"] = ex["free_float_pct"], ex["sources"]["free_float"]
    elif lh.get("free_float_pct") is not None:
        out["free_float_pct"], src["free_float"] = lh["free_float_pct"], lh_page("free_float")
    else:
        out["free_float_pct"] = None
    out["free_float_max_pct"] = ex.get("free_float_max_pct")
    if out["free_float_pct"] is None and ex.get("free_float_max_pct") is not None:
        src["free_float"] = ex["sources"]["free_float_max"]
    out["revenue_history"] = ex.get("revenue_history")
    out["year"] = year
    if ex.get("revenue_history"):
        src["revenue_history"] = ex["sources"]["revenue_history"]
    return out, src


def _cagr(val, n):
    """Revenue CAGR over n years, from years+1 consecutive audited figures that
    end in the latest audited year; None when the series is not complete.
    Lighthouse shows one actual year plus estimates, so the series comes from
    the accounts (data/extracted)."""
    hist = val["revenue_history"]               # {year: revenue_m}, actuals only
    ys = sorted(hist)[-(n + 1):] if hist else []
    if len(ys) == n + 1 and ys[-1] - ys[0] == n and ys[-1] == val["year"] and hist[ys[0]] > 0:
        return round(((hist[ys[-1]] / hist[ys[0]]) ** (1 / n) - 1) * 100, 1)
    return None


def evaluate(company, lh, filing, cfg, ex=None):
    F = cfg["filters"]
    res, notes = {}, {}
    val, src = inputs(lh, ex)
    ex = ex or {}
    judged = ex.get("judgements", {})

    m = company.get("market_cap_eur")
    m = float(m) if m not in (None, "") else None
    res["C1"] = NEEDS if m is None else (PASS if F["C1"]["min_eur"] <= m <= F["C1"]["max_eur"] else FAIL)

    # C2: the sector decides; outside it, only a documented judgement can pass.
    if company.get("sector") in F["C2"]["sectors"]:
        res["C2"], notes["C2"] = PASS, "sector " + company["sector"]
    elif "C2" in judged:
        res["C2"], notes["C2"] = judged["C2"]["verdict"], "judged"
    else:
        res["C2"], notes["C2"] = FAIL, "sector " + str(company.get("sector"))

    cagr = _cagr(val, F["C3"]["years"])
    res["C3"] = NEEDS if cagr is None else (PASS if cagr >= F["C3"]["min_pct"] else FAIL)

    # C4: insider holdings are a lower bound (only listed holders are added);
    # a strict free float gives an upper bound (insiders <= 100 - free float).
    bar = F["C4"]["min_pct"]
    ins, ff = ex.get("insider_pct"), ex.get("free_float_pct")
    if ins is not None and ins >= bar:
        res["C4"] = PASS
    elif ff is not None and 100 - ff < bar:
        res["C4"], notes["C4"] = FAIL, f"at most {round(100 - ff, 1)} (free float {ff})"
    elif ins is not None and ex.get("holders_complete"):
        res["C4"] = FAIL
    else:
        res["C4"] = NEEDS

    intl = ex.get("intl_pct")
    res["C5"] = NEEDS if intl is None else (PASS if intl >= F["C5"]["min_pct"] else FAIL)

    res["C6"] = judged["C6"]["verdict"] if "C6" in judged else NEEDS

    # An opinion read on its page (data/extracted) overrides the text parse,
    # which cannot see reports printed as images.
    op = ex.get("opinion", filing.get("opinion"))
    gc = ex.get("going_concern", filing.get("going_concern"))
    src["opinion"] = ex["sources"].get("opinion") if "opinion" in ex else (
        {"file": filing.get("file"), "page": "-", "method": "text-layer regex"} if op or gc else None)
    if op in ("QUALIFIED", "ADVERSE", "DISCLAIMER") or gc:
        res["C7"] = FAIL
    elif op == "CLEAN":
        res["C7"] = PASS
    else:
        res["C7"] = NEEDS                                     # opinion not read

    verdict = FAIL if FAIL in res.values() else NEEDS if NEEDS in res.values() else PASS
    exs = ex.get("sources", {})
    return {
        "isin": company["isin"], "name": company["name"], "sector": company.get("sector"),
        "market_cap_eur_m": round(m / 1e6, 1) if m else None,
        "revenue_eur_m": val["revenue_m"], "revenue_cagr_3y_pct": cagr,
        "insider_pct": ins, "free_float_pct": ff, "intl_revenue_pct": intl,
        "fiscal_year": val["year"], "lighthouse_year": lh.get("actual_year"),
        "auditor": filing.get("auditor"), "audit_opinion": op, "going_concern": gc,
        "restatement_declared": filing.get("restatement_declared"),
        **res, "verdict": verdict,
        "fails": ";".join(k for k, v in res.items() if v == FAIL),
        "needs_data": ";".join(k for k, v in res.items() if v == NEEDS),
        "note_C2": notes.get("C2"), "note_C4": notes.get("C4"),
        "judgement_C2": judged.get("C2", {}).get("text"),
        "judgement_C6": judged.get("C6", {}).get("text"),
        "src_revenue": _fmt(src.get("revenue")),
        "src_revenue_history": "; ".join(f"{y}: {_fmt(v)}" for y, v in
                                         sorted((src.get("revenue_history") or {}).items())) or None,
        "src_insider": _fmt(exs.get("insider")), "src_free_float": _fmt(src.get("free_float")),
        "src_intl": _fmt(exs.get("intl")),
        "src_judgement_C2": _fmt(exs.get("judgement_C2")),
        "src_judgement_C6": _fmt(exs.get("judgement_C6")),
        "src_opinion": _fmt(src.get("opinion")),
    }


# What an agent has to read or judge for each open filter.
TASKS = {
    "C2": ("filter", "sector is not 06: read the activity note and judge whether technology is "
                     "the product ([[judgement]] filter = \"C2\")"),
    "C3": ("reader", "read revenue for the last audited year and the three before "
                     "([[figure]] metric = \"revenue\", one per year)"),
    "C4": ("shareholders", "read every founder, director and manager holding "
                           "([[figure]] metric = \"insider_holding_pct\"; holders_complete = true "
                           "when the list is complete)"),
    "C5": ("reader", "read revenue outside Spain from the segment note "
                     "([[figure]] metric = \"intl_revenue_pct\")"),
    "C6": ("filter", "look for a published growth plan or guidance with quantified, dated targets "
                     "([[judgement]] filter = \"C6\")"),
    "C7": ("reader", "read the audit opinion and the going-concern section "
                     "([[figure]] metric = \"audit_opinion\" and \"going_concern\")"),
}
# Cheapest first: an agent stops reading a company at its first FAIL.
ORDER = ("C2", "C7", "C3", "C4", "C5", "C6")


def todo(screened, readable=None, closed=None):
    """The agents' work queue: for each company still open, the next filter to
    read or judge. A company with a FAIL needs nothing more, and neither does
    one without accounts to read (`readable`: ISINs whose filing is in hand).
    `closed` ({isin: {filter}}) holds the filters an agent has already written
    up as not readable ([open.Cn] in data/extracted): they are not asked again."""
    out = []
    for r in screened:
        if readable is not None and r["isin"] not in readable:
            continue
        done = (closed or {}).get(r["isin"], set())
        if r["verdict"] == FAIL and not (r["fails"] == "C2" and r.get("note_C2", "").startswith("sector")):
            continue
        open_ = [k for k in ORDER if k not in done and (r[k] == NEEDS or (
            k == "C2" and r[k] == FAIL and str(r.get("note_C2")).startswith("sector")))]
        if open_:
            agent, task = TASKS[open_[0]]
            out.append({"isin": r["isin"], "name": r["name"], "filter": open_[0],
                        "agent": agent, "task": task, "open": ";".join(open_)})
    return out
