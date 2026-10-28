# bme-growth-screener

Screens the BME Growth universe against eight criteria fixed in advance (`config/criteria.toml`): `python -m screener run` (live, BME API) or `python -m screener run --offline` (committed snapshot + cached PDFs).
Needs Python 3.11+, `pip install -r requirements.txt` and poppler's `pdftotext` on PATH. Missing data is reported as NEEDS_DATA, never PASS.
