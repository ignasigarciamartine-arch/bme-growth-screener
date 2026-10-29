"""Reading the auditor from the text of a filing."""
import os

import pytest

from screener import parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALQUIBER_FY2025 = os.path.join(ROOT, "cache", "text", "05366_OtraInfRelev_20260408.txt")


def test_auditor_is_the_firm_named_most_not_the_first_of_the_list():
    # Deloitte comes first in the list of firms and is cited as an adviser;
    # the report is signed by BDO.
    text = ("Las cuentas han sido auditadas por BDO.\f"
            "Matriz de riesgos con la firma externa Deloitte.\f"
            "BDO Auditores, S.L.P. es miembro de la red internacional de BDO.")
    assert parse.auditor_firm(text) == "BDO"


def test_auditor_tie_goes_to_the_firm_named_first():
    assert parse.auditor_firm("Informe de auditoria de KPMG. Antes, PwC.") == "KPMG"


def test_no_firm_named_gives_none():
    assert parse.auditor_firm("Informe de auditoria independiente") is None
    assert parse.auditor_firm(None) is None


@pytest.mark.skipif(not os.path.exists(ALQUIBER_FY2025), reason="Alquiber text not in cache/ yet")
def test_alquiber_fy2025_auditor_is_bdo():
    text = parse.pdf_text(None, ALQUIBER_FY2025)
    assert parse.audit_signals(text)["auditor"] == "BDO"
