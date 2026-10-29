"""The filters C1-C7 on the criteria in config/criteria.toml, at their edges,
and the rule every filter shares: missing data is NEEDS_DATA, never PASS."""
import os
import tomllib

import pytest

from screener import extracted, screen, verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "config", "criteria.toml"), "rb") as fh:
    CFG = tomllib.load(fh)

SRC = {"file": "x.pdf", "page": 1, "method": "pdftotext"}


def company(mcap=50e6, sector="06"):
    return {"isin": "XX0000000000", "name": "TEST", "market_cap_eur": mcap, "sector": sector}


def figures(revenue=20.0, history=None, insider=30.0, free_float=None, holders_complete=False,
            intl=40.0, opinion="CLEAN", going_concern=False, judgements=("C6",)):
    """Inputs as extracted.figures() returns them (EUR millions)."""
    ex = {"year": 2025, "sources": {}, "holders_complete": holders_complete}
    if revenue is not None:
        ex["revenue_m"], ex["sources"]["revenue"] = revenue, SRC
    if history is None and revenue is not None:
        history = {2022: revenue / 2, 2023: revenue / 1.6, 2024: revenue / 1.3, 2025: revenue}
    if history is not None:
        ex["revenue_history"] = history
        ex["sources"]["revenue_history"] = {y: SRC for y in history}
    if insider is not None:
        ex["insider_pct"], ex["sources"]["insider"] = insider, [SRC]
    if free_float is not None:
        ex["free_float_pct"], ex["sources"]["free_float"] = free_float, SRC
    if intl is not None:
        ex["intl_pct"], ex["sources"]["intl"] = intl, SRC
    if opinion is not None:
        ex["opinion"], ex["sources"]["opinion"] = opinion, SRC
    if going_concern is not None:
        ex["going_concern"], ex["sources"]["going_concern"] = going_concern, SRC
    ex["judgements"] = {}
    for j in judgements:
        k, v = (j, "PASS") if isinstance(j, str) else j
        ex["judgements"][k] = {"filter": k, "verdict": v, "text": "t", **SRC}
        ex["sources"]["judgement_" + k] = SRC
    return ex


def run(c=None, ex=None, lh=None, filing=None):
    return screen.evaluate(c or company(), lh or {}, filing or {}, CFG, ex)


# ------------------------------------------------- missing data is never a PASS

def test_complete_figures_pass():
    assert run(ex=figures())["verdict"] == "PASS"


def test_nothing_known_is_needs_data():
    r = run(company(mcap=None), ex=None)
    assert r["verdict"] == "NEEDS_DATA"
    assert all(r[f] == "NEEDS_DATA" for f in ("C1", "C3", "C4", "C5", "C6", "C7"))


@pytest.mark.parametrize("missing", ["history", "insider", "intl", "opinion", "judgements"])
def test_one_missing_input_is_needs_data(missing):
    kw = {missing: {} if missing == "history" else () if missing == "judgements" else None}
    r = run(ex=figures(**kw))
    assert r["verdict"] == "NEEDS_DATA", r


def test_a_fail_beats_missing_data():
    r = run(company(sector="02"), ex=figures(insider=None, intl=None))
    assert r["verdict"] == "FAIL" and r["fails"] == "C2"


# ---------------------------------------------------------------- edge cases

@pytest.mark.parametrize("mcap,expected", [(4_999_999, "FAIL"), (5_000_000, "PASS"),
                                           (80_000_000, "PASS"), (80_000_001, "FAIL")])
def test_c1_ticket_band_inclusive(mcap, expected):
    assert run(company(mcap), ex=figures())["C1"] == expected


def test_c2_sector_06_passes_and_others_fail_unless_judged():
    assert run(company(sector="06"), ex=figures())["C2"] == "PASS"
    assert run(company(sector="03"), ex=figures())["C2"] == "FAIL"
    judged = figures(judgements=("C6", ("C2", "PASS")))
    assert run(company(sector="03"), ex=judged)["C2"] == "PASS"


@pytest.mark.parametrize("first,expected", [(10.0 / 1.2 ** 3, "PASS"), (10.0 / 1.199 ** 3, "FAIL")])
def test_c3_twenty_percent_cagr(first, expected):
    r = run(ex=figures(revenue=10.0, history={2022: first, 2023: 8.0, 2024: 9.0, 2025: 10.0}))
    assert r["C3"] == expected


@pytest.mark.parametrize("history", [
    {2023: 10.0, 2024: 11.0, 2025: 12.0},                  # three figures, four needed
    {2021: 9.0, 2023: 10.0, 2024: 11.0, 2025: 12.0},       # a gap in the series
    {2021: 9.0, 2022: 10.0, 2023: 11.0, 2024: 12.0},       # does not end in the latest year
])
def test_c3_incomplete_series_is_needs_data(history):
    assert run(ex=figures(revenue=12.0, history=history))["C3"] == "NEEDS_DATA"


def test_c4_insider_lower_bound_passes_only_at_the_bar():
    assert run(ex=figures(insider=20.0))["C4"] == "PASS"
    assert run(ex=figures(insider=19.9))["C4"] == "NEEDS_DATA"          # other holders may exist
    assert run(ex=figures(insider=19.9, holders_complete=True))["C4"] == "FAIL"


def test_c4_free_float_upper_bound_can_fail():
    assert run(ex=figures(insider=None, free_float=85.0))["C4"] == "FAIL"
    assert run(ex=figures(insider=None, free_float=60.0))["C4"] == "NEEDS_DATA"


@pytest.mark.parametrize("intl,expected", [(24.9, "FAIL"), (25.0, "PASS")])
def test_c5_international_share(intl, expected):
    assert run(ex=figures(intl=intl))["C5"] == expected


def test_c6_is_the_judgement():
    assert run(ex=figures(judgements=(("C6", "FAIL"),)))["C6"] == "FAIL"
    assert run(ex=figures(judgements=()))["C6"] == "NEEDS_DATA"


@pytest.mark.parametrize("op,gc,expected", [
    ("CLEAN", False, "PASS"), ("QUALIFIED", False, "FAIL"), ("ADVERSE", False, "FAIL"),
    ("DISCLAIMER", False, "FAIL"), ("CLEAN", True, "FAIL"), (None, None, "NEEDS_DATA"),
])
def test_c7_opinion(op, gc, expected):
    assert run(ex=figures(opinion=op, going_concern=gc))["C7"] == expected


def test_domestic_revenue_gives_the_share_outside_spain():
    entry = {"file": "x.toml", "figures": [
        {"metric": "revenue", "year": 2025, "value": 18_000_000, "scale": 1, **SRC},
        {"metric": "domestic_revenue", "year": 2025, "value": 6_300_000, "scale": 1, **SRC}],
        "judgements": [], "holders_complete": False}
    assert extracted.figures(entry)["intl_pct"] == 65.0


# ---------------------------------------------------- the agents' work queue

def test_todo_asks_the_cheapest_open_filter_first_and_skips_closed_ones():
    open_ = run(ex=figures(opinion=None, insider=None))
    assert screen.todo([open_])[0]["filter"] == "C7"
    assert screen.todo([open_], closed={open_["isin"]: {"C7"}})[0]["filter"] == "C4"
    assert screen.todo([run(ex=figures())]) == []                     # a PASS needs nothing
    non_tech = run(company(sector="03"), ex=figures(insider=None))
    assert screen.todo([non_tech])[0]["filter"] == "C2"               # sector fail: judge it


# ---------------------------------------------------- verification step

def test_unconfirmed_pass_goes_back_to_needs_data():
    row = run(ex=figures())
    assert row["verdict"] == "PASS"
    verify.verify(row, {}, {}, ex=None, entry=None, cache=None)    # nothing to confirm with
    assert row["verdict"] == "NEEDS_DATA" and "verify" in row["needs_data"]


def test_figure_missing_from_its_file_demotes_a_pass(tmp_path):
    ex = figures()
    entry = {"figures": [{"metric": "revenue", "year": 2025, "value": 20e6, "scale": 1,
                          "file": "absent.pdf", "page": 1, "method": "pdftotext"}],
             "judgements": [{"filter": "C6", "verdict": "PASS", "text": "t",
                             "file": "absent.pdf", "page": 1, "method": "agent-read"}]}
    row = run(ex=ex)
    _, checks = verify.verify(row, {}, {}, ex, entry, str(tmp_path))
    assert {c["check"] for c in checks} == {"NO_FILE"}
    assert row["verdict"] == "NEEDS_DATA"
