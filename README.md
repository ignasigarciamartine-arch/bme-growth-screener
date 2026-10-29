# bme-growth-screener

Screens every company listed on BME Growth, the Spanish growth market, against eight criteria written down before the data was opened. It rebuilds the universe as of a date from the public BME API, pulls each candidate's audited accounts and holdings filings, applies seven hard filters in code and leaves the eighth for a person. On the 28 Oct 2026 universe: 109 listed, 55 operating companies once the property vehicles are removed, 35 candidates in the EUR 10-200M band, and 21 FAIL / 10 NEEDS_DATA / 4 PASS. The four that pass F1-F7 are Alquiber Quality, Energy Solar Tech, Seresco and Vytrus Biotech.

Example output: [`examples/report-2026-10-28.html`](examples/report-2026-10-28.html), a copy of the `runs/2026-10-28/report.html` that the pipeline writes. It is one self-contained file: download it and open it in a browser (GitHub shows only the source). Figures taken from filings link to the PDF at the page they were read from.

## Quickstart

Python 3.11 or later. No system tools: PDFs are read with pypdfium2, a pip wheel that bundles PDFium.

```
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m screener run --as-of 2026-10-28
python -m pytest
```

`run --as-of 2026-10-28` reads the versioned snapshot in `data/snapshots/2026-10-28/` (the universe and the list of documents for that date) and downloads the documents it lists from the BME API and the Lighthouse site into `cache/`. The first run fetches about 1 GB; later runs read the cache. Output goes to `runs/2026-10-28/`: `report.html`, `screened.csv` (one row per candidate, with a source for every filter input), `funnel.md` and the check files.

| Flag | What it does |
|---|---|
| `--offline` | No network: the snapshot and `cache/` only. Stops with a message if the snapshot is missing. |
| `--rebuild-snapshot` | Rebuilds the universe and the document list from the BME API before running. A date with no snapshot is rebuilt anyway. |
| `--no-ocr` | Skips the OCR re-check of figures read on page images. |

Rebuilding is why snapshots are versioned. Market cap uses the last close on or before the date, and the 2026-10-28 snapshot was taken during that day, with the 27 Oct close. Rebuilt the next day it takes the 28 Oct close: same 109 companies and same documents, different prices, same verdicts.

Tesseract is optional. With it, every run searches the figures read on scanned pages again by OCR; without it the verdicts are the same and the run lists the figures it could not re-check. Install it with `winget install UB-Mannheim.TesseractOCR` (Windows), `brew install tesseract` (macOS) or `sudo apt install tesseract-ocr` (Debian/Ubuntu), or point the `TESSERACT` variable at the executable.

`python -m pytest` runs 51 tests. Three need the downloaded documents and are skipped until the first run has filled `cache/`.

## Method

### Criteria first

The eight filters live in `config/criteria.toml` and were fixed on 25 Jul 2026, before the universe was examined. The frame is a mandate for EUR 1-10M of minority growth capital in a listed small cap.

| | Filter | Threshold |
|---|---|---|
| F1 | Market capitalisation | EUR 10-200M |
| F2 | Revenue, last audited year | at least EUR 5M |
| F3 | EBITDA, last audited year | positive |
| F4 | Revenue CAGR, 3 years | at least 0% |
| F5 | Net financial debt / EBITDA | at most 3.5x |
| F6 | Free float | at least 15% |
| F7 | Audit opinion | clean, no material uncertainty on going concern |
| F8 | Catalyst and instrument fit | manual |

Thresholds are never edited in place. A change goes into the `[[changelog]]` of the same file with its date, filter and reason, and applies to every company. There is one entry so far: on 28 Jul 2026 the F6 definition was made precise (who counts as excluded from free float), with the threshold unchanged, because one company read 14.5% or 22.0% depending on the definition. It was applied retroactively to every screened company, not only to the survivors.

### Missing data is NEEDS_DATA, never PASS

A filter that cannot be evaluated is NEEDS_DATA, and one NEEDS_DATA keeps a company out of the passes. A bound built from holdings that the F6 definition excludes can fail free float but never pass it.

### Automatic and documented readings

Every filter input in `screened.csv` is tagged with its source. *Auto* inputs (45 on the 2026-10-28 run) come from the code: market cap from the BME API, the first-page table of the Lighthouse sheets, the opinion regex. *Documented* inputs (94) come from readings made page by page and versioned in `data/extracted/<date>/<ISIN>.toml`, each with value, scale, fiscal year, file, page and method. Every run looks for each of the 93 readings again on its page: in the text layer for the 64 read from text, and for the 29 read on page images, in the text layer first and then by local OCR. The results go to `extracted_check.csv`. A text-layer figure that is no longer on its page sends a PASS back to NEEDS_DATA; an OCR miss is reported and leaves the verdict alone.

### Audited accounts over third-party sheets

The accounts are the primary source. A Lighthouse sheet (independent coverage of BME Growth companies) fills a gap only for the same fiscal year, and a figure that decides a case is checked against the accounts.

## What went wrong along the way

- **Going-concern regex:** the July 2026 version failed Umbrella Global on F7 for a going-concern uncertainty. The match was the standard responsibilities paragraph that every Spanish audit report carries ("concluimos sobre si existe o no una incertidumbre material..."). The rule now counts only the auditor's own section heading, or the finding itself.
- **Robot, read as clean:** its FY2025 report is a scan. The text layer held only the company's own pages, where the directors are asked to ensure that the accounts give a true and fair view, and the parser took that sentence for a clean opinion. OCR of page 3 shows a qualified opinion from RSM (loans to loss-making subsidiaries not impaired). It is a documented reading now, and F7 fails.
- **Facephi, opinion out of reach:** the parser reads a fixed window after the first "informe de auditoría" heading. In the FY2025 pack that heading is in the company's cover letter on page 1, and the qualification in the consolidated report (a scope limitation on R&D financing agreements) is on page 35, past the window. The parser returned no opinion, so F7 stayed NEEDS_DATA rather than passing. The page-35 reading closed it as FAIL.
- **PDFs inside PDFs:** Lleida.net files its accounts as a PDF portfolio: the consolidated accounts and the audit report are attachments nested two levels down, and the text parser saw only a 7-page cover. The pipeline now saves embedded PDFs, two levels deep, and cites them by file and page like any other document.
- **A pass with no data behind it:** in the July 2026 version Seresco came out PASS with no three-year revenue series and an audit opinion that was only on a scanned page. With the rule above enforced it dropped to NEEDS_DATA. It passes now because both are read from the accounts, with their pages.
- **Wrong auditor:** the parser took the first firm of its list found anywhere in the filing, so Alquiber came out as audited by Deloitte, which the filing cites as an outside adviser on risk controls (p. 109). The auditor is BDO (p. 3). It now takes the firm named most often, which also corrected six other filings. No verdict uses this field.

## Applying this to early-stage deals

A pre-seed or seed company has no audited accounts or holdings filings, but the same habits carry over.

- **Cap table before the deck:** at seed stage the shareholder table does the work of the holdings filings. It shows who owns what on which terms, and so how much room the round has. Read it before the narrative.
- **Reconcile the pitch with the books:** match the deck's revenue and ARR to recognised revenue in the management accounts and to cash in the bank statements, month by month. Each gap gets a written explanation and the document it comes from.
- **Criteria before the pitch, with a changelog:** write the thresholds for a fund thesis before the first meeting. When one changes, log the date and the reason and re-apply it to every company already seen, so each decision traces back to the rules that produced it.
- **A sourcing agent:** the harvest step generalises. Pull public signals (registry filings, funding announcements) into a dated snapshot, run the written criteria over it and hand a person a short list with a source for every line. It narrows the list; it does not decide.

## Limits

- F8, catalyst and instrument fit, is not scored. A pass means F1-F7 are met on documented figures, nothing more.
- 10 of the 35 candidates are still NEEDS_DATA: accounts filed but not yet read page by page, accounts mostly scanned, no FY2025 accounts filed, no accounts in BME at all, or, for NZI Helmets, an F6 that the filings cannot decide. The report gives the reason for each.
- Free float is taken in its strictest reading where the filings leave room: for Vytrus Biotech every holder of 5% or more counts as excluded, whether or not the definition would exclude it.
- This is a screening tool. Nothing in it is investment advice.

## Repository

```
config/criteria.toml        criteria F1-F8, fixed 2026-07-25, with changelog
data/snapshots/<date>/      universe and document list per date (versioned)
data/extracted/<date>/      documented readings, one TOML per company
screener/                   pipeline: harvest -> parse -> screen -> verify -> report
  templates/report.html     template of the HTML report
tests/                      pytest
examples/                   report written by the 2026-10-28 run
cache/, runs/               downloaded documents and run outputs (not versioned)
```
