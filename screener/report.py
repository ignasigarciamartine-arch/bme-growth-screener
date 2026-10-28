"""Step 5: write the run to disk and print the funnel."""
import csv
import os


def _csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def funnel_lines(stages, screened, cfg):
    u = cfg["universe"]
    v = {k: [r for r in screened if r["verdict"] == k] for k in ("PASS", "NEEDS_DATA", "FAIL")}
    after = [r["name"] for r in stages["listed"] if r.get("mcap_basis") == "latest_close_after_as_of"]
    lines = [
        f"BME Growth screen | universe as of {u['as_of']} | criteria fixed {cfg['criteria']['fixed_on']}",
        "",
        f"  Listed in {u['market']:<34}{len(stages['listed']):>5}",
        f"  - SOCIMIs (property vehicles){'':<15}{-len(stages['excluded_subsector']):>5}",
        f"  = Operating companies{'':<23}{len(stages['operating']):>5}",
        f"  - Outside F1 band (EUR 10-200M){'':<13}{-len(stages['outside_band']):>5}",
        f"  = Inside the band{'':<27}{len(stages['in_band']):>5}",
        f"  - Excluded by name (see config){'':<13}{-len(stages['excluded_isin']):>5}",
        f"  = Candidates screened{'':<23}{len(stages['candidates']):>5}",
        "",
        f"  Automated filters F1-F7 (F8 is manual):",
        f"    FAIL       {len(v['FAIL']):>3}",
        f"    NEEDS_DATA {len(v['NEEDS_DATA']):>3}",
        f"    PASS       {len(v['PASS']):>3}",
    ]
    if after:
        lines += ["", f"  Note: no price history before as_of for {', '.join(after)};",
                  "        latest close used for F1 (all far outside the band)."]
    return lines


def write(out_dir, stages, screened, checks, cfg):
    os.makedirs(out_dir, exist_ok=True)
    stage_rows = []
    for r in stages["listed"]:
        isin = r["isin"]
        if r in stages["excluded_subsector"]:
            stage = "excluded: SOCIMI"
        elif r in stages["outside_band"]:
            stage = "excluded: outside F1 band"
        elif any(x["isin"] == isin for x in stages["excluded_isin"]):
            stage = "excluded: " + next(x["reason"] for x in stages["excluded_isin"] if x["isin"] == isin)
        else:
            stage = "candidate"
        stage_rows.append({**r, "stage": stage})
    _csv(os.path.join(out_dir, "universe_stages.csv"), stage_rows)
    order = {"PASS": 0, "NEEDS_DATA": 1, "FAIL": 2}
    screened = sorted(screened, key=lambda r: (order[r["verdict"]], r["name"]))
    _csv(os.path.join(out_dir, "screened.csv"), screened)
    _csv(os.path.join(out_dir, "verify.csv"), checks)

    lines = funnel_lines(stages, screened, cfg)
    md = ["# Funnel", "", "```", *lines, "```", "", "## Screened candidates", "",
          "| Company | Verdict | Fails | Needs data |", "|---|---|---|---|"]
    md += [f"| {r['name']} | {r['verdict']} | {r['fails'] or '-'} | {r['needs_data'] or '-'} |"
           for r in screened]
    with open(os.path.join(out_dir, "funnel.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    return lines
