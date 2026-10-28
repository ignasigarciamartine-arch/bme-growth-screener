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


def evaluate(company, lh, filing, cfg):
    F = cfg["filters"]
    res, notes = {}, {}

    m = company.get("market_cap_eur")
    m = float(m) if m not in (None, "") else None
    res["F1"] = NEEDS if m is None else (PASS if F["F1"]["min_eur"] <= m <= F["F1"]["max_eur"] else FAIL)

    rev, ebitda = lh.get("revenue_m"), lh.get("ebitda_m")
    nd, ff = lh.get("net_debt_m"), lh.get("free_float_pct")

    res["F2"] = NEEDS if rev is None else (PASS if rev >= F["F2"]["min_eur_m"] else FAIL)
    res["F3"] = NEEDS if ebitda is None else (PASS if ebitda > 0 else FAIL)

    # F4 needs years+1 audited revenue figures. Neither source gives a series
    # of actuals today (Lighthouse shows one actual year plus estimates), so it
    # stays open until someone reads the history from the accounts.
    hist = lh.get("revenue_history")            # {year: revenue_m}, actuals only
    n = F["F4"]["years"]
    if hist and len(hist) >= n + 1:
        ys = sorted(hist)[-(n + 1):]
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

    res["F6"] = NEEDS if ff is None else (PASS if ff >= F["F6"]["min_pct"] else FAIL)

    op = filing.get("opinion")
    if op in ("QUALIFIED", "ADVERSE", "DISCLAIMER") or filing.get("going_concern"):
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
        "nd_ebitda": notes.get("F5"), "free_float_pct": ff, "lighthouse_year": lh.get("actual_year"),
        "auditor": filing.get("auditor"), "audit_opinion": op,
        "going_concern": filing.get("going_concern"),
        "restatement_declared": filing.get("restatement_declared"),
        **res, "verdict": verdict,
        "fails": ";".join(k for k, v in res.items() if v == FAIL),
        "needs_data": ";".join(k for k, v in res.items() if v == NEEDS),
    }
