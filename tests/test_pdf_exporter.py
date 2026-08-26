"""Tests for CV PDF export."""
from utils.pdf_exporter import export_cv_to_pdf


def test_export_cv_to_pdf_returns_pdf_bytes():
    pdf = export_cv_to_pdf(
        "SUMMARY\nExperienced engineer.\n\nSKILLS\nPython, Django, AWS"
    )
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500


def test_export_cv_to_pdf_handles_empty_text():
    pdf = export_cv_to_pdf("")
    assert pdf[:5] == b"%PDF-"


def test_export_cv_to_pdf_handles_headers_without_blank_line_separator():
    pdf = export_cv_to_pdf("SUMMARY\nA capable engineer.\nSKILLS\nPython")
    assert pdf[:5] == b"%PDF-"
