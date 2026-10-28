"""python -m screener run [--as-of YYYY-MM-DD] [--offline] [--rebuild-snapshot] [--no-ocr]

harvest -> parse -> screen -> verify -> report

The universe and the list of documents for a date are a versioned snapshot in
data/snapshots/<as_of>/. A run uses that snapshot when it exists and downloads
the documents it lists that are not in the cache yet (BME API and the
Lighthouse site, both public), so the same date gives the same result on any
machine. Without a snapshot for the date, or with --rebuild-snapshot, the
snapshot is rebuilt from the BME API and the Lighthouse index first.
--offline never touches the network: the snapshot and the cache only.
Everything is read and written inside the repository (config/, data/, cache/,
runs/), unless --cache or --out say otherwise.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

from . import env

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _snapshot_dir(as_of):
    return os.path.join(ROOT, "data", "snapshots", as_of.isoformat())


def harvest(cfg, as_of, cache, offline, rebuild, log):
    from . import screen, sources, universe
    snap = _snapshot_dir(as_of)
    have = os.path.exists(os.path.join(snap, "universe.csv")) and \
        os.path.exists(os.path.join(snap, "documents.json"))
    if offline and not have:
        raise SystemExit(f"--offline needs a snapshot for {as_of}: {snap} does not exist.")
    if have and not rebuild:
        with open(os.path.join(snap, "universe.csv"), encoding="utf-8") as f:
            uni = list(csv.DictReader(f))
        with open(os.path.join(snap, "documents.json"), encoding="utf-8") as f:
            docs = json.load(f)
        rel = os.path.relpath(snap, ROOT)
        log(f"[harvest] versioned snapshot {rel} ({len(uni)} companies, "
            f"{'cache only' if offline else 'downloading what the cache lacks'})")
    else:
        log(f"[harvest] rebuilding the snapshot: universe of {cfg['universe']['segment']} on {as_of}")
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
    for key in ("filing", "filing_prior"):
        sources.detach_attachments({k: v[key] for k, v in docs.items() if key in v}, cache, log)
    sources.download_filings({k: v["holdings"] for k, v in docs.items() if "holdings" in v},
                             cache, offline, log, folder="holdings")
    sources.download_lighthouse({k: v["lighthouse"] for k, v in docs.items()}, cache, offline, log)
    return uni, docs


def run(args, log=print):
    import tomllib

    from . import extracted, parse, pdf, report, screen, verify
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    as_of = dt.date.fromisoformat(args.as_of or cfg["universe"]["as_of"])
    cfg["universe"]["as_of"] = as_of.isoformat()

    ocr_exe = None if args.no_ocr else pdf.tesseract()
    uni, docs = harvest(cfg, as_of, args.cache, args.offline, args.rebuild_snapshot, log)

    log("[parse] accounts and Lighthouse sheets")
    parsed = {}
    for isin, d in docs.items():
        fl, lh = d["filing"], d["lighthouse"]
        pf = {}
        if fl["status"] == "OK":
            pdf_file = os.path.join(args.cache, "filings", fl["file"])
            txt = os.path.join(args.cache, "text", fl["file"][:-4] + ".txt")
            pf = parse.parse_filing(pdf_file, txt)
            pf["restatement_declared"] = fl.get("restatement_declared")
            pf["year"] = fl.get("year")
        pl = {}
        if lh["status"] == "OK":
            pl = parse.parse_lighthouse(os.path.join(args.cache, "lighthouse", lh["file"]))
        parsed[isin] = {"filing": pf, "lighthouse": pl}

    ex = extracted.load(ROOT, as_of.isoformat())
    log(f"[extracted] documented readings for {len(ex)} companies "
        f"(data/extracted/{as_of.isoformat()})")
    figs = {isin: extracted.figures(e) for isin, e in ex.items()}

    log("[screen] funnel and filters F1-F7")
    stages = screen.funnel(uni, cfg)
    screened = [screen.evaluate(c, parsed[c["isin"]]["lighthouse"], parsed[c["isin"]]["filing"], cfg,
                                figs.get(c["isin"]))
                for c in stages["candidates"]]

    if ocr_exe:
        log(f"[verify] revenue against the accounts; documented readings re-checked "
            f"(OCR: {ocr_exe})")
    else:
        log("[verify] revenue against the accounts; documented readings re-checked "
            "(OCR " + ("disabled with --no-ocr)" if args.no_ocr else "not available)"))
    checks, figure_checks = [], []
    for r in screened:
        c, fc = verify.verify(r, parsed[r["isin"]]["lighthouse"], parsed[r["isin"]]["filing"],
                              figs.get(r["isin"]), ex.get(r["isin"]), args.cache, ocr_exe)
        checks.append(c)
        figure_checks += fc

    notes = []
    missing = [(d["name"], k, d[k]["status"]) for d in docs.values()
               for k in ("filing", "filing_prior", "holdings", "lighthouse")
               if k in d and d[k]["status"] in ("NOT_IN_CACHE", "DOWNLOAD_FAILED")]
    if missing:
        notes += ["", f"  WARNING: {len(missing)} documents of the snapshot are not available "
                  "(their filters stay NEEDS_DATA):"]
        notes += [f"    {n}: {k} {s}" for n, k, s in missing]
    if not ocr_exe and not args.no_ocr:
        notes += ["", "  WARNING: Tesseract not found, so the documented readings on page images",
                  "  were not re-verified on this machine. They still count, with their page.",
                  "  " + pdf.TESSERACT_HINT]
    out = os.path.join(args.out, as_of.isoformat())
    lines = report.write(out, stages, screened, checks, cfg, figure_checks, ocr_exe is not None, notes)
    with open(os.path.join(out, "parsed.json"), "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=1)
    log("[report] " + out)
    log("")
    log("\n".join(lines))
    return screened


def main(argv=None):
    p = argparse.ArgumentParser(prog="screener")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="harvest -> parse -> screen -> verify -> report")
    r.add_argument("--as-of", help="universe date (default: config)")
    r.add_argument("--offline", action="store_true",
                   help="no network: the versioned snapshot and the cache only")
    r.add_argument("--rebuild-snapshot", action="store_true",
                   help="rebuild data/snapshots/<as_of> from the BME API even if it exists")
    r.add_argument("--no-ocr", action="store_true",
                   help="do not OCR page images (verdicts never depend on OCR)")
    r.add_argument("--config", default=os.path.join(ROOT, "config", "criteria.toml"))
    r.add_argument("--cache", default=os.path.join(ROOT, "cache"))
    r.add_argument("--out", default=os.path.join(ROOT, "runs"))
    a = p.parse_args(argv)
    if a.offline and a.rebuild_snapshot:
        p.error("--offline and --rebuild-snapshot exclude each other")
    env.check()
    if a.cmd == "run":
        run(a)


if __name__ == "__main__":
    sys.exit(main())
