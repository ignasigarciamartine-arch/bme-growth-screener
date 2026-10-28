"""The filters F1-F7 on the criteria in config/criteria.toml, at their edges,
and the rule every filter shares: missing data is NEEDS_DATA, never PASS."""
import os
import tomllib

import pytest

from screener import screen, verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "config", "criteria.toml"), "rb") as fh:
    CFG = tomllib.load(fh)


def company(mcap=50e6):
    return {"isin": "XX0000000000", "name": "TEST", "market_cap_eur": mcap}


def figures(revenue=20.0, ebitda=4.0, net_debt=2.0, free_float=30.0,
            history=None, opinion="CLEAN", going_concern=False, free_float_max=None):
    """Inputs as extracted.figures() returns them (EUR millions)."""
    src = {"file": "x.pdf", "page": 1, "method": "pdftotext"}
    ex = {"year": 2025, "sources": {}}
    for key, name, v in (("revenue_m", "revenue", revenue), ("ebitda_m", "ebitda", ebitda),
                         ("net_debt_m", "net_debt", net_debt),
                         ("free_float_pct", "free_float", free_float)):
        if v is not None:
            ex[key], ex["sources"][name] = v, src
    if history is None and revenue is not None:
        history = {2022: revenue / 1.3, 2023: revenue / 1.2, 2024: revenue / 1.1, 2025: revenue}
    if history is not None:
        ex["revenue_history"] = history
        ex["sources"]["revenue_history"] = {y: src for y in history}
    if opinion is not None:
        ex["opinion"], ex["sources"]["opinion"] = opinion, src
    if going_concern is not None:
        ex["going_concern"], ex["sources"]["going_concern"] = going_concern, src
    if free_float_max is not None:
        ex["free_float_max_pct"] = free_float_max
        ex["sources"]["free_float_max"] = [src]
    return ex


def run(c=None, ex=None, lh=None, filing=None):
    return screen.evaluate(c or company(), lh or {}, filing or {}, CFG, ex)


# ------------------------------------------------- missing data is never a PASS

def test_complete_figures_pass():
    assert run(ex=figures())["verdict"] == "PASS"


def test_nothing_known_is_needs_data():
    r = run(company(mcap=None), ex=None)
    assert r["verdict"] == "NEEDS_DATA"
    assert all(r[f] == "NEEDS_DATA" for f in ("F1", "F2", "F3", "F4", "F5", "F6", "F7"))


@pytest.mark.parametrize("missing", ["revenue", "ebitda", "net_debt", "free_float",
                                     "history", "opinion"])
def test_one_missing_input_is_needs_data(missing):
    kw = {missing: None}
    if missing == "history":
        kw["history"] = {}                                 # None would mean "default series"
    r = run(ex=figures(**kw))
    assert r["verdict"] == "NEEDS_DATA", r


def test_missing_market_cap_is_needs_data():
    r = run(company(mcap=None), ex=figures())
    assert r["F1"] == "NEEDS_DATA" and r["verdict"] == "NEEDS_DATA"


def test_a_fail_beats_missing_data():
    r = run(ex=figures(revenue=1.0, history={2022: 1, 2023: 1, 2024: 1, 2025: 1.0},
                       free_float=None))
    assert r["verdict"] == "FAIL" and "F2" in r["fails"]


# ---------------------------------------------------------------- edge cases

@pytest.mark.parametrize("mcap,expected", [(9_999_999, "FAIL"), (10_000_000, "PASS"),
                                           (200_000_000, "PASS"), (200_000_001, "FAIL")])
def test_f1_band_inclusive(mcap, expected):
    assert run(company(mcap), ex=figures())["F1"] == expected


@pytest.mark.parametrize("rev,expected", [(4.99, "FAIL"), (5.0, "PASS")])
def test_f2_revenue_floor(rev, expected):
    assert run(ex=figures(revenue=rev))["F2"] == expected


@pytest.mark.parametrize("ebitda,expected", [(-0.1, "FAIL"), (0.0, "FAIL"), (0.01, "PASS")])
def test_f3_ebitda_strictly_positive(ebitda, expected):
    assert run(ex=figures(ebitda=ebitda))["F3"] == expected


def test_f4_flat_revenue_fails():
    r = run(ex=figures(history={2022: 10.0, 2023: 11.0, 2024: 9.0, 2025: 10.0}, revenue=10.0))
    assert r["F4"] == "FAIL" and r["revenue_cagr_3y_pct"] == 0.0


def test_f4_growth_passes():
    r = run(ex=figures(history={2022: 10.0, 2023: 10.0, 2024: 10.0, 2025: 10.1}, revenue=10.1))
    assert r["F4"] == "PASS"


@pytest.mark.parametrize("history", [
    {2023: 10.0, 2024: 11.0, 2025: 12.0},                  # three figures, four needed
    {2021: 9.0, 2023: 10.0, 2024: 11.0, 2025: 12.0},       # a gap in the series
    {2021: 9.0, 2022: 10.0, 2023: 11.0, 2024: 12.0},       # does not end in the latest year
])
def test_f4_incomplete_series_is_needs_data(history):
    assert run(ex=figures(revenue=12.0, history=history))["F4"] == "NEEDS_DATA"


@pytest.mark.parametrize("nd,ebitda,expected", [
    (3.49 * 4, 4.0, "PASS"), (3.5 * 4, 4.0, "FAIL"),       # below 3.5x passes, 3.5x does not
    (-1.0, 4.0, "PASS"),                                   # net cash
    (-1.0, None, "PASS"),                                  # net cash needs no EBITDA
    (2.0, -1.0, "N/A"),                                    # ratio meaningless; F3 fails instead
    (2.0, None, "NEEDS_DATA"),
])
def test_f5_leverage(nd, ebitda, expected):
    assert run(ex=figures(net_debt=nd, ebitda=ebitda))["F5"] == expected


@pytest.mark.parametrize("ff,expected", [(14.99, "FAIL"), (15.0, "PASS")])
def test_f6_free_float(ff, expected):
    assert run(ex=figures(free_float=ff))["F6"] == expected


def test_f6_upper_bound_can_fail_but_never_pass():
    assert run(ex=figures(free_float=None, free_float_max=11.8))["F6"] == "FAIL"
    assert run(ex=figures(free_float=None, free_float_max=80.0))["F6"] == "NEEDS_DATA"


@pytest.mark.parametrize("op,gc,expected", [
    ("CLEAN", False, "PASS"), ("QUALIFIED", False, "FAIL"), ("ADVERSE", False, "FAIL"),
    ("DISCLAIMER", False, "FAIL"), ("CLEAN", True, "FAIL"), (None, None, "NEEDS_DATA"),
])
def test_f7_opinion(op, gc, expected):
    assert run(ex=figures(opinion=op, going_concern=gc))["F7"] == expected


def test_lighthouse_of_another_year_is_not_mixed_in():
    """Accounts say FY2025; a 2024 Lighthouse sheet cannot fill the EBITDA gap."""
    lh = {"actual_year": "2024A", "ebitda_m": 5.0, "file": "lh.pdf", "rows": {}}
    assert run(ex=figures(ebitda=None), lh=lh)["F3"] == "NEEDS_DATA"


# ---------------------------------------------------- verification step

def test_unconfirmed_pass_goes_back_to_needs_data():
    row = run(ex=figures())
    assert row["verdict"] == "PASS"
    verify.verify(row, {}, {}, ex=None, entry=None, cache=None)    # nothing to confirm with
    assert row["verdict"] == "NEEDS_DATA" and "verify" in row["needs_data"]


def test_figure_missing_from_its_file_demotes_a_pass(tmp_path):
    ex = figures()
    ex["sources"]["revenue"] = {"file": "absent.pdf", "page": 1, "method": "pdftotext"}
    entry = {"figures": [{"metric": "revenue", "year": 2025, "value": 20e6, "scale": 1,
                          "file": "absent.pdf", "page": 1, "method": "pdftotext"}]}
    row = run(ex=ex)
    _, checks = verify.verify(row, {}, {}, ex, entry, str(tmp_path))
    assert checks[0]["check"] == "NO_FILE"
    assert row["verdict"] == "NEEDS_DATA"
