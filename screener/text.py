"""Text helpers shared by every step."""
import re
import unicodedata


def deaccent(s):
    """pdftotext returns accents inconsistently depending on the PDF generator;
    normalising stops patterns from failing silently."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def norm_name(s):
    s = deaccent(s).upper()
    s = re.sub(r"\b(S\.?A\.?U?|S\.?L\.?U?|SAD|SOCIMI|GROUP|GRUPO|HOLDING)\b", " ", s)
    return re.sub(r"[^A-Z0-9]+", "", s)


def es_number(tok):
    """'1.234.567,89' or '(1.234)' -> float. Parentheses mean negative."""
    tok = tok.strip()
    neg = tok.startswith("(") and tok.endswith(")")
    t = tok.strip("()").replace(".", "").replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v
