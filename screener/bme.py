"""Thin client for the public BME market-data API (apiweb.bolsasymercados.es).

Only the endpoints the screener needs. No authentication; the API is the one
behind the BME Growth website.
"""
import time

import requests

API = "https://apiweb.bolsasymercados.es/Market/"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def get(path, retries=3, **params):
    params.setdefault("language", "es")
    for attempt in range(retries):
        try:
            r = requests.get(API + path, headers=HEADERS, params=params, timeout=60)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.json()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def paged(path, **params):
    """Follow `hasMoreResults` until the endpoint is exhausted."""
    out, page = [], 0
    while True:
        d = get(path, page=page, pageSize=50, **params)
        out += d.get("data", [])
        if not d.get("hasMoreResults"):
            return out
        page += 1
        time.sleep(0.15)


def listed_companies(segment):
    return paged("v1/EQ/ListedCompanies", tradingSystem="MTF", mtfSegment=segment)


def share_details(isin):
    """Works for delisted shares too: returns sector, shares, issuer code."""
    return get("v1/EQ/ShareDetailsInfo", isin=isin)


def corporate_actions(kind, segment, date_from, date_to):
    """kind: 'NewListings' or 'Delistings'. Dates as YYYYMMDD."""
    return paged(f"v1/EQ/CorporateActions/{kind}", tradingSystem="MTF",
                 mtfSegment=segment, **{"from": date_from, "to": date_to})


def closes(isin, date_from, date_to):
    return paged("v1/EQ/HistoricalSharesPrices", isin=isin,
                 **{"from": date_from, "to": date_to})


def financial_information(year_from, year_to):
    """Every annual / audit filing (document type 001) in the period."""
    return paged("v1/EQ/MtfEquity/FinancialInformation", fromYear=year_from,
                 toYear=year_to, order="Period DESC")


def download_document(url_path, dest):
    """Filing URLs are relative to the API root. Returns True on a real PDF."""
    r = requests.get(API.rstrip("/") + url_path, headers={"User-Agent": "Mozilla/5.0"},
                     timeout=120)
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        with open(dest, "wb") as f:
            f.write(r.content)
        return True
    return False
