# bme-growth-screener

Screens the BME Growth universe against eight criteria fixed in advance (`config/criteria.toml`). Missing data is reported as NEEDS_DATA, never PASS.

## Install and run

Python 3.11 or later. No system tools are required: PDFs are read with pypdfium2 (a wheel that bundles PDFium).

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python -m screener run --as-of 2026-10-28
.venv/bin/python -m pytest
```

`run --as-of DATE` uses the versioned snapshot in `data/snapshots/DATE/` and downloads the documents it lists (about 1 GB for 2026-10-28) from the public BME API and the Lighthouse site into `cache/`. Output goes to `runs/DATE/`.

- `--offline`: no network, snapshot and `cache/` only.
- `--rebuild-snapshot`: rebuild the snapshot from the BME API (also what happens for a date with no snapshot).
- `--no-ocr`: skip the OCR re-check.

Optional: Tesseract OCR re-verifies the figures read from page images (`data/extracted/`). Without it the run gives the same result and says which figures it could not re-verify. Install: Windows `winget install UB-Mannheim.TesseractOCR`, macOS `brew install tesseract`, Debian/Ubuntu `sudo apt install tesseract-ocr`, or set `TESSERACT` to the executable.
