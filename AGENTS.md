# Running the screen with your AI

This repository is a screening workflow for every company on BME Growth, run by
AI agents on top of plain Python tools. Claude Code reads `.claude/agents/` and
the `/screen` command; Codex and other agents read this file. The steps are the
same.

## The split

- **Code does what must not vary between models.** Downloading the universe and
  the filings from the exchange's public API, applying C1-C7 to the figures,
  checking every figure on the page it cites, writing the report.
  `python -m screener run` and `python -m screener todo`.
- **Agents do what code cannot.** Reading figures off scanned pages and broken
  tables, telling a founder's holding from a fund's, judging whether
  technology is the product (C2 outside sector 06) and whether the company has
  published a growth plan with quantified, dated targets (C6). Every reading and judgement is written to
  `data/extracted/<as_of>/<ISIN>.toml` with its file and page.

## Rules the agents must not break

1. Never edit `config/criteria.toml` during a run. A change of criteria is a
   human decision, appended to its `[[changelog]]`.
2. Every figure and judgement cites a file and a page of a document in
   `cache/`. No file, no figure. Never type a figure you did not read.
3. A figure you cannot find is not written. The filter stays NEEDS_DATA; if
   you looked and it is not in the documents, say so in `[open.Cn]`.
4. The verifier is code. If it reports NOT_FOUND or NO_FILE, fix the reading;
   do not argue with it.
5. Stop reading a company at its first FAIL.

## The loop

```
python -m screener run --as-of 2026-10-28     # downloads, screens, writes runs/<as_of>/todo.csv
python -m screener todo --as-of 2026-10-28    # next filter to read or judge, per company
```

Then, for each line of `todo`, the agent named in it does its task (see
`.claude/agents/`), writes the TOML, and the loop runs again until `todo` is
empty. `todo` asks for the cheapest filter first: C2, C7, C3, C4, C5, C6.

| Agent | Filters | Reads |
|---|---|---|
| orchestrator | all | runs the loop, hands out the queue, never reads a PDF itself |
| reader | C3, C5, C7 | annual accounts: revenue series, geographic segment note, audit opinion |
| shareholders | C4 | significant-holdings filing and the board list in the accounts |
| filter | C2, C6 | activity note, published plans and guidance; writes a judgement with reasons |

To read a page, use the text layer first; for scanned pages, OCR
(`screener.pdf.ocr_page`) or the page image. Record `method = "pdftotext"`
for the text layer, `"ocr"` for OCR text, `"agent-read"` for a page image you
read yourself.

## TOML formats

See the docstring of `screener/extracted.py`. In short:

```toml
[[figure]]
metric = "revenue"           # revenue, insider_holding_pct, domestic_revenue,
year = 2025                  # intl_revenue_pct, audit_opinion, going_concern, ...
value = 36_543_950
scale = 1                    # 1 euros, 1000 thousands, "pct" percent
file = "05509_OtraInfRelev_20260429.pdf"
page = 47
method = "pdftotext"
note = "Consolidated P&L, Importe neto de la cifra de negocios"

[[judgement]]
filter = "C6"                # C2 or C6
verdict = "FAIL"             # PASS or FAIL
text = "Why, in two or three sentences, with the numbers."
file = "05509_OtraInfRelev_20260429.pdf"
page = 9
method = "agent-read"

[open.C3]                    # looked, not in the documents
text = "No accounts before FY2024 in the snapshot."
refs = ["05818_OtraInfRelev_20260430_1.pdf#17"]
```

Results can differ a little between models on readings of scanned pages and
on the two judgements. The verifier keeps the figures honest; the
judgements are written out so a human can disagree with them.
