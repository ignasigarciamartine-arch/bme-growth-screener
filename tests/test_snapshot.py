"""The funnel of the versioned snapshot of 2026-10-28.

The funnel counts need only the snapshot (versioned). The verdicts need the
documents too: that test runs the pipeline offline against cache/ and is
skipped while the cache does not hold them (run `python -m screener run
--as-of 2026-10-28` once to download them).
"""
import argparse
import csv
import json
import os
import tomllib

import pytest

from screener import __main__ as cli
from screener import extracted, screen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AS_OF = "2026-10-28"
SNAP = os.path.join(ROOT, "data", "snapshots", AS_OF)
CACHE = os.path.join(ROOT, "cache")
PASS = {"SERESCO", "ALQUIBER QUALITY", "ENERGY SOLAR TECH", "VYTRUS BIOTECH"}


def cfg():
    with open(os.path.join(ROOT, "config", "criteria.toml"), "rb") as fh:
        c = tomllib.load(fh)
    c["universe"]["as_of"] = AS_OF
    return c


def universe():
    with open(os.path.join(SNAP, "universe.csv"), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_funnel_counts():
    s = screen.funnel(universe(), cfg())
    assert len(s["listed"]) == 109
    assert len(s["excluded_subsector"]) == 54
    assert len(s["operating"]) == 55
    assert len(s["outside_band"]) == 16
    assert len(s["in_band"]) == 39
    assert len(s["excluded_isin"]) == 4
    assert len(s["candidates"]) == 35


def test_snapshot_lists_documents_for_every_candidate():
    with open(os.path.join(SNAP, "documents.json"), encoding="utf-8") as fh:
        docs = json.load(fh)
    cands = {c["isin"] for c in screen.funnel(universe(), cfg())["candidates"]}
    assert set(docs) == cands


def test_documented_readings_load_and_cite_file_and_page():
    ex = extracted.load(ROOT, AS_OF)
    assert len(ex) == 13
    for isin, e in ex.items():
        for f in e["figures"]:
            assert f["file"].endswith(".pdf") and f["page"] >= 1, (isin, f)


def _documents_cached():
    with open(os.path.join(SNAP, "documents.json"), encoding="utf-8") as fh:
        docs = json.load(fh)
    folders = {"filing": "filings", "filing_prior": "filings", "holdings": "holdings",
               "lighthouse": "lighthouse"}
    return all(os.path.exists(os.path.join(CACHE, folders[k], d[k]["file"]))
               for d in docs.values() for k in folders
               if k in d and d[k].get("status") == "OK")


@pytest.mark.skipif(not _documents_cached(), reason="documents not in cache/ yet")
def test_verdicts_from_the_cached_documents(tmp_path):
    args = argparse.Namespace(config=os.path.join(ROOT, "config", "criteria.toml"), as_of=AS_OF,
                              cache=CACHE, out=str(tmp_path), offline=True,
                              rebuild_snapshot=False, no_ocr=True)
    screened = cli.run(args, log=lambda *a: None)
    by = {}
    for r in screened:
        by.setdefault(r["verdict"], set()).add(r["name"])
    assert {k: len(v) for k, v in by.items()} == {"FAIL": 21, "NEEDS_DATA": 10, "PASS": 4}
    assert by["PASS"] == PASS
