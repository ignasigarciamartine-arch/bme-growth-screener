"""Step 4: check the screening figures against the audited accounts.

Lighthouse is the comparable source; the accounts are the primary one. Here
revenue, the figure every filter downstream leans on, is looked up among the
candidate lines read from the accounts (with file and page). A PASS whose
revenue cannot be found in the accounts goes back to NEEDS_DATA. Both fiscal
years are written out: a DISCREPANCY is often a stale sheet, not a wrong number.
"""
TOLERANCE = 0.02


def _match(target_m, candidates, units):
    for c in candidates:
        for v in c["vals"]:
            for scale in {units, 1, 1000}:
                got = abs(v) * scale / 1e6
                if target_m and abs(got - abs(target_m)) <= TOLERANCE * abs(target_m):
                    return {"value_eur_m": round(got, 2), "page": c["page"], "line": c["line"]}
    return None


def verify(row, lh, filing):
    out = {"isin": row["isin"], "name": row["name"], "metric": "revenue",
           "lighthouse_eur_m": lh.get("revenue_m"), "lighthouse_file": lh.get("file"),
           "lighthouse_page": (lh.get("rows", {}).get("revenue") or {}).get("page"),
           "lighthouse_year": lh.get("actual_year"),
           "accounts_file": filing.get("file"), "accounts_year": filing.get("year")}
    if lh.get("revenue_m") is None:
        out["status"] = "NO_COMPARABLE_FIGURE"
    elif not filing.get("revenue"):
        out["status"] = "NOT_IN_ACCOUNTS_TEXT"
    else:
        hit = _match(lh["revenue_m"], filing["revenue"], filing.get("units", 1))
        if hit:
            out.update(status="CONFIRMED", accounts_eur_m=hit["value_eur_m"],
                       accounts_page=hit["page"], accounts_line=hit["line"])
        else:
            c = filing["revenue"][0]
            out.update(status="DISCREPANCY", accounts_page=c["page"], accounts_line=c["line"])
    if row["verdict"] == "PASS" and out["status"] != "CONFIRMED":
        row["verdict"] = "NEEDS_DATA"
        row["needs_data"] = ";".join(x for x in (row["needs_data"], "verify") if x)
    return out
