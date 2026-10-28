"""Everything the screener does with a PDF, through pypdfium2 (a pip wheel that
bundles PDFium), so no system tool is needed to read the documents:

  * text of each page (the text layer),
  * embedded PDFs (accounts filed as attachments of a cover PDF),
  * one page rendered to an image, for OCR.

OCR itself is optional and is the only external program: Tesseract. Without it
the pipeline still runs; the figures read from page images are reported as not
re-verified on this machine.
"""
import os
import shutil
import subprocess
import tempfile

import pypdfium2 as pdfium

TESSERACT_HINT = (
    "Tesseract OCR is optional (it re-verifies the figures read from page images). "
    "Install it with: Windows `winget install UB-Mannheim.TesseractOCR`, "
    "macOS `brew install tesseract`, Debian/Ubuntu `sudo apt install tesseract-ocr`, "
    "or point the TESSERACT environment variable at the executable.")


def page_texts(pdf):
    """Text layer of every page, in order. Line breaks normalised to \\n."""
    doc = pdfium.PdfDocument(pdf)
    try:
        out = []
        for i in range(len(doc)):
            page = doc[i]
            tp = page.get_textpage()
            out.append(tp.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n"))
            tp.close()
            page.close()
        return out
    finally:
        doc.close()


def attachments(pdf):
    """[(n, name, bytes)] of the embedded files, n 1-based in document order."""
    doc = pdfium.PdfDocument(pdf)
    try:
        out = []
        for i in range(doc.count_attachments()):
            a = doc.get_attachment(i)
            out.append((i + 1, a.get_name(), bytes(a.get_data())))
        return out
    finally:
        doc.close()


def render(pdf, page, dpi=300):
    """One page (1-based) as a PIL image."""
    doc = pdfium.PdfDocument(pdf)
    try:
        p = doc[page - 1]
        img = p.render(scale=dpi / 72).to_pil()
        p.close()
        return img
    finally:
        doc.close()


def tesseract():
    """Path of the Tesseract executable, or None."""
    exe = os.environ.get("TESSERACT")
    if exe and os.path.exists(exe):
        return exe
    exe = shutil.which("tesseract")
    if exe:
        return exe
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.exists(p):
            return p
    return None


def _langs(exe):
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True,
                             timeout=30).stdout
    except (subprocess.SubprocessError, OSError):
        return set()
    return {x.strip() for x in out.splitlines()[1:] if x.strip()}


def ocr_page(pdf, page, exe, psm="3"):
    """OCR text of one page (Spanish model if installed, else English).
    psm 3 (automatic layout) reads most scanned statements; 6 (one block of
    text) is the fallback for pages that 3 splits badly."""
    langs = _langs(exe)
    lang = "spa" if "spa" in langs else "eng"
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "page.png")
        render(pdf, page).convert("L").save(png)
        r = subprocess.run([exe, png, "stdout", "-l", lang, "--psm", psm],
                           capture_output=True, timeout=300)
    return r.stdout.decode("utf-8", "replace")
