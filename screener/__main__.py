"""python -m screener run [--as-of YYYY-MM-DD] [--offline]

harvest -> parse -> screen -> verify -> report

Live mode rebuilds the snapshot in data/snapshots/<as_of>/ from the BME API
and the Lighthouse index, and downloads the documents into the cache.
Offline mode reads the committed snapshot and the cached documents only.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
import tomllib

from . import extracted, parse, report, screen, sources, universe, verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _snapshot_dir(as_of):
    return os.path.join(ROOT, "data", "snapshots", as_of.isoformat())


def harvest(cfg, as_of, cache, offline, log):
    snap = _snapshot_dir(as_of)
    if offline:
        with open(os.path.join(snap, "universe.csv"), encoding="utf-8") as f:
            uni = list(csv.DictReader(f))
        with open(os.path.join(snap, "documents.json"), encoding="utf-8") as f:
            docs = json.load(f)
        log(f"[harvest] offline: snapshot {snap} ({len(uni)} companies)")
    else:
        log(f"[harvest] universe of {cfg['universe']['segment']} on {as_of}")
        uni = universe.build(as_of, cfg["universe"]["segment"], log=log)
        cands = screen.funnel(uni, cfg)["candidates"]
        log(f"[harvest] documents for {len(cands)} candidates")
        filings = sources.harvest_filings(cands, as_of, log=log)
        holdings = sources.harvest_holdings(cands, as_of, log=log)
        sheets = sources.harvest_lighthouse(cands, as_of, log=log)
        docs = {c["isin"]: {"name": c["name"], "filing": filings[c["isin"]][0],
                            "filing_prior": filings[c["isin"]][1],
                            "holdings": holdings[c["isin"]],
                            "lighthouse": sheets[c["isin"]]} for c in cands}
        os.makedirs(snap, exist_ok=True)
        with open(os.path.join(snap, "universe.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=universe.FIELDS)
            w.writeheader()
            w.writerows(uni)
        with open(os.path.join(snap, "documents.json"), "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=1)
    sources.download_filings({k: v["filing"] for k, v in docs.items()}, cache, offline, log)
    # Snapshots taken before 2026-10-28 do not record the prior accounts.
    sources.download_filings({k: v["filing_prior"] for k, v in docs.items() if "filing_prior" in v},
                             cache, offline, log)
    sources.download_filings({k: v["holdings"] for k, v in docs.items() if "holdings" in v},
                             cache, offline, log, folder="holdings")
    sources.download_lighthouse({k: v["lighthouse"] for k, v in docs.items()}, cache, offline, log)
    return uni, docs


def run(args):
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    as_of = dt.date.fromisoformat(args.as_of or cfg["universe"]["as_of"])
    cfg["universe"]["as_of"] = as_of.isoformat()
    log = print

    uni, docs = harvest(cfg, as_of, args.cache, args.offline, log)

    log("[parse] accounts and Lighthouse sheets")
    parsed = {}
    for isin, d in docs.items():
        fl, lh = d["filing"], d["lighthouse"]
        pf = {}
        if fl["status"] == "OK":
            pdf = os.path.join(args.cache, "filings", fl["file"])
            txt = os.path.join(args.cache, "txt", fl["file"][:-4] + ".txt")
            pf = parse.parse_filing(pdf, txt)
            pf["restatement_declared"] = fl.get("restatement_declared")
            pf["year"] = fl.get("year")
        pl = {}
        if lh["status"] == "OK":
            pl = parse.parse_lighthouse(os.path.join(args.cache, "lighthouse", lh["file"]))
        parsed[isin] = {"filing": pf, "lighthouse": pl}

    ex = extracted.load(ROOT, as_of.isoformat())
    log(f"[extracted] figures read from the documents for {len(ex)} companies "
        f"(data/extracted/{as_of.isoformat()})")
    figs = {isin: extracted.figures(e) for isin, e in ex.items()}

    log("[screen] funnel and filters F1-F7")
    stages = screen.funnel(uni, cfg)
    screened = [screen.evaluate(c, parsed[c["isin"]]["lighthouse"], parsed[c["isin"]]["filing"], cfg,
                                figs.get(c["isin"]))
                for c in stages["candidates"]]

    log("[verify] revenue against the audited accounts")
    checks, figure_checks = [], []
    for r in screened:
        c, fc = verify.verify(r, parsed[r["isin"]]["lighthouse"], parsed[r["isin"]]["filing"],
                              figs.get(r["isin"]), ex.get(r["isin"]), args.cache)
        checks.append(c)
        figure_checks += fc

    out = os.path.join(args.out, as_of.isoformat())
    lines = report.write(out, stages, screened, checks, cfg, figure_checks)
    with open(os.path.join(out, "parsed.json"), "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=1)
    log("[report] " + out)
    log("")
    log("\n".join(lines))


def main(argv=None):
    p = argparse.ArgumentParser(prog="screener")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="harvest -> parse -> screen -> verify -> report")
    r.add_argument("--as-of", help="universe date (default: config)")
    r.add_argument("--offline", action="store_true", help="use the committed snapshot and the cache")
    r.add_argument("--config", default=os.path.join(ROOT, "config", "criteria.toml"))
    r.add_argument("--cache", default=os.path.join(ROOT, "cache"))
    r.add_argument("--out", default=os.path.join(ROOT, "runs"))
    a = p.parse_args(argv)
    if a.cmd == "run":
        run(a)


if __name__ == "__main__":
    sys.exit(main())
