"""What the pipeline needs from the machine, checked before anything runs.

Required: Python 3.11+ and the packages in requirements.txt. Nothing else: the
PDFs are read with pypdfium2, a wheel that bundles PDFium.
Optional: Tesseract OCR, which re-verifies the figures read from page images.
"""
import importlib
import sys

REQUIRED = [("requests", "requests"), ("pdfplumber", "pdfplumber"), ("pypdfium2", "pypdfium2"),
            ("PIL", "Pillow")]


class MissingDependency(SystemExit):
    pass


def check():
    """Raise MissingDependency with an actionable message, or return None."""
    if sys.version_info < (3, 11):
        raise MissingDependency(
            f"screener needs Python 3.11 or later (tomllib); this is {sys.version.split()[0]}.")
    missing = []
    for module, package in REQUIRED:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    if missing:
        raise MissingDependency(
            f"Missing Python packages: {', '.join(missing)}.\n"
            f"Install them in this environment with:  {sys.executable} -m pip install -r requirements.txt")
