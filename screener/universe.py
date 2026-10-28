"""Step 1a: the listed universe of a BME segment as it stood on a given date.

The API only lists what is listed today, so the universe on `as_of` is rebuilt:

    listed today
  + delisted after as_of        (they were still there on as_of)
  - new listings after as_of    (they were not there yet)

Market cap on as_of = shares on as_of x last close on or before as_of, where
shares on as_of = shares today - shares admitted (capital increases) after as_of.
"""
import datetime as dt
import time

from . import bme

FIELDS = ["isin", "name", "issuer_code", "sector", "subsector", "status",
          "shares_as_of", "close", "close_date", "market_cap_eur", "mcap_basis"]


def _ymd(d):
    return d.strftime("%Y%m%d")


def _last_close(isin, as_of):
    """Last traded close on or before as_of. Illiquid names may not have traded
    for months, so the window widens before giving up."""
    for days in (30, 400, 1830):
        rows = bme.closes(isin, _ymd(as_of - dt.timedelta(days=days)), _ymd(as_of))
        rows = [r for r in rows if r.get("close")]
        if rows:
            last = max(rows, key=lambda r: r["date"])
            return last["close"], last["date"]
    return None, None


def build(as_of, segment, log=print):
    today = dt.date.today()
    after_from, after_to = _ymd(as_of + dt.timedelta(days=1)), _ymd(today)

    listed = {c["isin"]: c for c in bme.listed_companies(segment)}
    if as_of < today:
        delisted = bme.corporate_actions("Delistings", segment, after_from, after_to)
        admissions = bme.corporate_actions("NewListings", segment, after_from, after_to)
    else:                             # universe as of today: nothing to undo
        delisted, admissions = [], []
    new = {a["isin"] for a in admissions if a.get("admissionType") == "NewListing"}
    added_shares = {}
    for a in admissions:
        if a.get("admissionType") != "NewListing":
            added_shares[a["isin"]] = added_shares.get(a["isin"], 0) + (a.get("numShares") or 0)

    isins = (set(listed) | {d["isin"] for d in delisted}) - new
    log(f"  listed today {len(listed)}, delisted after {as_of} {len(delisted)}, "
        f"new after {as_of} {len(new)} -> {len(isins)} on {as_of}")

    rows = []
    for isin in sorted(isins):
        info = bme.share_details(isin)
        shares = (info.get("shares") or 0) - added_shares.get(isin, 0)
        close, close_date = _last_close(isin, as_of)
        basis = "close_on_or_before_as_of"
        if close is None and info.get("lastClosePrice"):
            # No price history served for this share. Fall back to the latest
            # close and say so: this value post-dates as_of.
            close, close_date = info["lastClosePrice"], info.get("lastClosePriceDate")
            basis = "latest_close_after_as_of"
        elif close is None:
            basis = "missing"
        mcap = round(shares * close, 2) if close and shares > 0 else None
        rows.append({
            "isin": isin, "name": info.get("name") or listed.get(isin, {}).get("name"),
            "issuer_code": info.get("issuerCode"), "sector": info.get("sector"),
            "subsector": info.get("subsector"),
            "status": "listed" if isin in listed else "delisted_after_as_of",
            "shares_as_of": shares, "close": close, "close_date": close_date,
            "market_cap_eur": mcap, "mcap_basis": basis,
        })
        time.sleep(0.1)
    return rows
