"""Step 3: the funnel and the hard filters.

Rule for every filter: if it cannot be evaluated the result is NEEDS_DATA,
never PASS. Missing data is not favourable data.
"""
PASS, FAIL, NEEDS, NA, MANUAL = "PASS", "FAIL", "NEEDS_DATA", "N/A", "MANUAL"


def funnel(universe, cfg):
    """Universe -> operating -> inside the F1 band -> candidates."""
    u = cfg["universe"]
    sub = {(x["sector"], x["subsector"]): x["reason"] for x in u.get("exclude_subsector", [])}
    by_isin = {x["isin"]: x["reason"] for x in u.get("exclude_isin", [])}
    f1 = cfg["filters"]["F1"]

    stages = {"listed": universe}
    stages["excluded_subsector"] = [r for r in universe if (r["sector"], r["subsector"]) in sub]
    operating = [r for r in universe if (r["sector"], r["subsector"]) not in sub]
    stages["operating"] = operating

    def mcap(r):
        v = r.get("market_cap_eur")
        return float(v) if v not in (None, "") else None

    stages["outside_band"] = [r for r in operating
                              if mcap(r) is not None and not f1["min_eur"] <= mcap(r) <= f1["max_eur"]]
    # A company without a market cap is not dropped: F1 stays NEEDS_DATA.
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
    """F2-F6 inputs and where each comes from.

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
    for key, lh_key, row in (("revenue_m", "revenue_m", "revenue"), ("ebitda_m", "ebitda_m", "ebitda"),
                             ("net_debt_m", "net_debt_m", "net_debt")):
        name = row
        if ex.get(key) is not None:
            out[key], src[name] = ex[key], ex["sources"][name]
        elif lh_same_year and lh.get(lh_key) is not None:
            out[key], src[name] = lh[lh_key], lh_page(row)
        else:
            out[key] = None
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


def evaluate(company, lh, filing, cfg, ex=None):
    F = cfg["filters"]
    res, notes = {}, {}
    val, src = inputs(lh, ex)
    ex = ex or {}

    m = company.get("market_cap_eur")
    m = float(m) if m not in (None, "") else None
    res["F1"] = NEEDS if m is None else (PASS if F["F1"]["min_eur"] <= m <= F["F1"]["max_eur"] else FAIL)

    rev, ebitda = val["revenue_m"], val["ebitda_m"]
    nd, ff = val["net_debt_m"], val["free_float_pct"]

    res["F2"] = NEEDS if rev is None else (PASS if rev >= F["F2"]["min_eur_m"] else FAIL)
    res["F3"] = NEEDS if ebitda is None else (PASS if ebitda > 0 else FAIL)

    # F4 needs years+1 audited revenue figures, consecutive and ending in the
    # latest audited year. Lighthouse shows one actual year plus estimates, so
    # the series comes from the accounts (data/extracted) or stays open.
    hist = val["revenue_history"]               # {year: revenue_m}, actuals only
    n = F["F4"]["years"]
    ys = sorted(hist)[-(n + 1):] if hist else []
    if len(ys) == n + 1 and ys[-1] - ys[0] == n and ys[-1] == val["year"]:
        cagr = ((hist[ys[-1]] / hist[ys[0]]) ** (1 / n) - 1) * 100 if hist[ys[0]] > 0 else None
        res["F4"] = NEEDS if cagr is None else (PASS if cagr > F["F4"]["min_pct"] else FAIL)
        notes["F4"] = None if cagr is None else round(cagr, 1)
    else:
        res["F4"] = NEEDS

    if nd is None:
        res["F5"] = NEEDS
    elif nd < 0:
        res["F5"], notes["F5"] = PASS, 0.0                   # net cash
    elif ebitda is None:
        res["F5"] = NEEDS
    elif ebitda <= 0:
        res["F5"] = NA                                        # ratio meaningless; F3 already fails
    else:
        notes["F5"] = round(nd / ebitda, 2)
        res["F5"] = PASS if notes["F5"] < F["F5"]["max_x"] else FAIL

    if ff is not None:
        res["F6"] = PASS if ff >= F["F6"]["min_pct"] else FAIL
    elif val["free_float_max_pct"] is not None and val["free_float_max_pct"] < F["F6"]["min_pct"]:
        # Holders the definition excludes already leave less than the bar.
        res["F6"], notes["F6"] = FAIL, f"at most {val['free_float_max_pct']}"
    else:
        res["F6"] = NEEDS

    # An opinion read on its page (data/extracted) overrides the text parse,
    # which cannot see reports printed as images.
    op = ex.get("opinion", filing.get("opinion"))
    gc = ex.get("going_concern", filing.get("going_concern"))
    src["opinion"] = ex["sources"].get("opinion") if "opinion" in ex else (
        {"file": filing.get("file"), "page": "-", "method": "text-layer regex"} if op else None)
    if op in ("QUALIFIED", "ADVERSE", "DISCLAIMER") or gc:
        res["F7"] = FAIL
    elif op == "CLEAN":
        res["F7"] = PASS
    else:
        res["F7"] = NEEDS                                     # opinion not read

    res["F8"] = MANUAL

    auto = [res[k] for k in ("F1", "F2", "F3", "F4", "F5", "F6", "F7")]
    verdict = FAIL if FAIL in auto else NEEDS if NEEDS in auto else PASS
    return {
        "isin": company["isin"], "name": company["name"],
        "market_cap_eur_m": round(m / 1e6, 1) if m else None,
        "revenue_eur_m": rev, "ebitda_eur_m": ebitda, "net_debt_eur_m": nd,
        "nd_ebitda": notes.get("F5"), "free_float_pct": ff if ff is not None else notes.get("F6"), "revenue_cagr_3y_pct": notes.get("F4"),
        "fiscal_year": val["year"], "lighthouse_year": lh.get("actual_year"),
        "auditor": filing.get("auditor"), "audit_opinion": op,
        "going_concern": gc,
        "restatement_declared": filing.get("restatement_declared"),
        **res, "verdict": verdict,
        "fails": ";".join(k for k, v in res.items() if v == FAIL),
        "needs_data": ";".join(k for k, v in res.items() if v == NEEDS),
        "src_revenue": _fmt(src.get("revenue")), "src_ebitda": _fmt(src.get("ebitda")),
        "src_net_debt": _fmt(src.get("net_debt")), "src_free_float": _fmt(src.get("free_float")),
        "src_revenue_history": "; ".join(f"{y}: {_fmt(v)}" for y, v in
                                         sorted((src.get("revenue_history") or {}).items())) or None,
        "src_opinion": _fmt(src.get("opinion")),
    }
