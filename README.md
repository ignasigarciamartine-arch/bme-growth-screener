# bme-growth-screener

Screens every company listed on BME Growth, the Spanish growth market, against seven filters read from 4Founders Capital's four published investment criteria. Plain Python code rebuilds the universe as of a date from the public BME API, downloads each candidate's filings, applies the filters and checks every figure on its page. AI agents (Claude Code, Codex or any agent that reads `AGENTS.md`) do what the code cannot: read scanned pages, tell a founder's holding from a fund's, and judge, with file and page, whether technology is the product and whether a growth plan has been published.

On the 28 Oct 2026 universe: 109 listed, 55 operating companies once the SOCIMIs are removed, 35 inside the EUR 5-80M band, 34 candidates after one exclusion by name, and **1 PASS / 0 NEEDS_DATA / 33 FAIL**. The pass is Cuatroochenta.

Example output: [`examples/report-2026-10-28.html`](examples/report-2026-10-28.html), a copy of the `runs/2026-10-28/report.html` that the pipeline writes. It is one self-contained file: download it and open it in a browser (GitHub shows only the source). Figures taken from filings link to the PDF at the page they were read from. `dashboard/index.html` shows the workflow as a graph and `dashboard/results.html` the funnel and the pass.

## Run it with your AI

```
git clone https://github.com/ignasigarciamartine-arch/bme-growth-screener
cd bme-growth-screener
claude          # or: codex
/screen         # Claude Code; with Codex, ask it to follow AGENTS.md
```

`/screen` (`.claude/commands/screen.md`) makes the agent the orchestrator: it runs the code, reads the work queue, hands each item to the reader, shareholders or filter agent (`.claude/agents/`), and runs the code again until the queue is empty. `AGENTS.md` holds the same loop and the rules for agents other than Claude Code.

## Run the code alone

Python 3.11 or later. No system tools: PDFs are read with pypdfium2, a pip wheel that bundles PDFium.

```
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m screener run --as-of 2026-10-28
python -m screener todo --as-of 2026-10-28
python -m pytest
```

`run --as-of 2026-10-28` reads the versioned snapshot in `data/snapshots/2026-10-28/` (the universe and the list of documents for that date), downloads the documents it lists from the BME API and the Lighthouse site into `cache/`, and applies the readings already versioned in `data/extracted/2026-10-28/`. The first run fetches about 1 GB; later runs read the cache. Output goes to `runs/2026-10-28/`: `report.html`, `screened.csv` (one row per candidate, with a source for every filter input), `funnel.md`, `todo.csv` and the check files. `todo` prints the agents' work queue: per company, the next filter still to read or judge. With the readings in this repo it is empty.

| Flag | What it does |
|---|---|
| `--offline` | No network: the snapshot and `cache/` only. Stops with a message if the snapshot is missing. |
| `--rebuild-snapshot` | Rebuilds the universe and the document list from the BME API before running. A date with no snapshot is rebuilt anyway. |
| `--no-ocr` | Skips the OCR re-check of figures read on page images. |

Rebuilding is why snapshots are versioned. Market cap uses the last close on or before the date, and the 2026-10-28 snapshot was taken during that day, with the 27 Oct close. Rebuilt the next day it takes the 28 Oct close: same 109 companies and same documents, different prices.

Tesseract is optional. With it, every run searches the figures read on scanned pages again by OCR; without it the verdicts are the same and the run lists the figures it could not re-check. Install it with `winget install UB-Mannheim.TesseractOCR` (Windows), `brew install tesseract` (macOS) or `sudo apt install tesseract-ocr` (Debian/Ubuntu), or point the `TESSERACT` variable at the executable.

`python -m pytest` runs 42 tests. Three need the downloaded documents and are skipped until the first run has filled `cache/`.

## Method

### Seven filters, from 4Founders' published criteria

The filters live in `config/criteria.toml`. Each one names the published criterion it comes from; where the criterion gives no number, the bar is mine and the file says so.

| | Filter | Bar | Read by |
|---|---|---|---|
| C1 | Ticket fit (criterion 03) | Market cap EUR 5-80M, so a EUR 100K-4M ticket is about 5-20% of the company | code |
| C2 | Strong tech component (criterion 02) | BME sector 06; any other sector fails unless an agent shows, with file and page, that technology is the product | code + agent |
| C3 | Scale (criterion 02) | Revenue CAGR over 3 years of at least 20% | code |
| C4 | Ownership (criterion 01) | Founders, directors and management hold at least 20% | agent |
| C5 | International mindset (criterion 01) | At least 25% of revenue outside Spain | agent |
| C6 | Ambition (criterion 01) | A published growth plan with quantified targets and a date | agent |
| C7 | Clean accounts | Clean audit opinion, no material uncertainty on going concern | code + agent |

Before screening, the SOCIMIs (Spanish REITs) and two other property vehicles named in the config are removed: they are not operating companies.

Thresholds are never edited in place. A change goes into the `[[changelog]]` of the same file with its date, filter and reason, and applies to every company. The earlier criteria (F1-F8, a EUR 1-10M public-equity mandate) are replaced there by C1-C7 and remain in the git history.

### Code for what must not vary, agents for what code cannot read

The code downloads, applies the filters, verifies and writes the report, so those steps give the same answer whichever AI runs the loop. The agents read and judge, and write every reading to `data/extracted/<date>/<ISIN>.toml` with its value, scale, fiscal year, file, page and method; a judgement (C2, C6) carries its reasons. `todo` asks for the cheapest filter first (C2, C7, C3, C4, C5, C6) and an agent stops reading a company at its first FAIL, which is why most failing companies show other filters as not evaluated.

### Missing data is NEEDS_DATA, never PASS

A filter that cannot be evaluated is NEEDS_DATA, and one NEEDS_DATA keeps a company out of the passes.

### Every reading is checked on its page, by code

Every filter input in `screened.csv` is tagged with its source. *Auto* inputs (22 on the 2026-10-28 run) come from the code: the Lighthouse table and the opinion regex. *Documented* inputs (110) come from the 111 readings in `data/extracted/2026-10-28/`. Every run looks for each reading again on its page. For the 52 read from the text layer, the number is searched on its page: 41 found, and 11 are text values. For the 59 read on page images, the text layer comes first and then local OCR: 39 found by OCR, 4 in the text layer, and 16 the verifier can only confirm as cited on a page that exists. The results go to `extracted_check.csv`. A text-layer figure that is no longer on its page sends a PASS back to NEEDS_DATA; an OCR miss is reported and leaves the verdict alone.

### Audited accounts over third-party sheets

The accounts are the primary source. A Lighthouse sheet (independent coverage of BME Growth companies) fills a gap only for the same fiscal year, and a figure that decides a case is checked against the accounts.

## The result, 28 Oct 2026

- **PASS, Cuatroochenta:** market cap EUR 48.9M; revenue CAGR 25.5% (EUR 18.5M in 2022 to EUR 36.5M in 2025); its two CEOs hold 29.3%; more than 44% of revenue outside Spain; Guidance 2030 of EUR 70M revenue and EUR 10M EBITDA, approved by the board and published with the FY2025 accounts; clean opinion from Grant Thornton. Part of the growth comes from acquired companies; the guidance counts organic growth only.
- **FAIL, 33**, counted at the first filter failed: 20 on C2 (not technology companies), 5 on C3 (Making Science and Seresco at 18.3%, Catenon 9.2%, Gigas Hosting 6.6%, Lleida.net -2.2%), 5 on C7 (audit opinion qualified or a going-concern uncertainty), 2 on C6 (Optare Solutions, Substrate Artificial) and 1 on C5 (Tree Technology, 1.5% of revenue outside Spain).

## What went wrong along the way

- **Going-concern regex:** the July 2026 version failed Umbrella Global for a going-concern uncertainty. The match was the standard responsibilities paragraph that every Spanish audit report carries ("concluimos sobre si existe o no una incertidumbre material..."). The rule now counts only the auditor's own section heading, or the finding itself.
- **Robot, read as clean:** its FY2025 report is a scan. The text layer held only the company's own pages, where the directors are asked to ensure that the accounts give a true and fair view, and the parser took that sentence for a clean opinion. OCR of page 3 shows a qualified opinion from RSM (loans to loss-making subsidiaries not impaired). It is a documented reading now, and C7 fails.
- **Facephi, opinion out of reach:** the parser reads a fixed window after the first "informe de auditoría" heading. In the FY2025 pack that heading is in the company's cover letter on page 1, and the qualification in the consolidated report (a scope limitation on R&D financing agreements) is on page 35, past the window. The parser returned no opinion, so the filter stayed NEEDS_DATA rather than passing. The page-35 reading closed it as FAIL.
- **PDFs inside PDFs:** Lleida.net files its accounts as a PDF portfolio: the consolidated accounts and the audit report are attachments nested two levels down, and the text parser saw only a 7-page cover. The pipeline now saves embedded PDFs, two levels deep, and cites them by file and page like any other document.
- **A pass with no data behind it:** in the July 2026 version Seresco came out PASS with no three-year revenue series and an audit opinion that was only on a scanned page. With the rule above enforced it dropped to NEEDS_DATA. Both are read from the accounts now, with their pages, and under C1-C7 it fails C3 at 18.3%.
- **Wrong auditor:** the parser took the first firm of its list found anywhere in the filing, so Alquiber came out as audited by Deloitte, which the filing cites as an outside adviser on risk controls (p. 109). The auditor is BDO (p. 3). It now takes the firm named most often, which also corrected six other filings. No verdict uses this field.

## Limits

- A pass means C1-C7 are met on documented figures, nothing more. It is where a first call starts, not an investment case.
- C2 and C6 are judgements. They cite file and page; the verifier confirms the page exists, not that the judgement is right.
- This is a screening tool. Nothing in it is investment advice.

## Repository

```
AGENTS.md                   the loop and the rules, for any agent
.claude/commands/screen.md  /screen for Claude Code
.claude/agents/             orchestrator, reader, shareholders, filter
config/criteria.toml        criteria C1-C7, with changelog
data/snapshots/<date>/      universe and document list per date (versioned)
data/extracted/<date>/      readings and judgements, one TOML per company
screener/                   code: harvest -> parse -> screen -> verify -> report, and todo
dashboard/                  index.html (workflow) and results.html (funnel and pass)
tests/                      pytest
examples/                   report written by the 2026-10-28 run
cache/, runs/               downloaded documents and run outputs (not versioned)
```
