"""Tests for resume text extraction across supported file types."""
import pytest
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from utils.parser import (
    SUPPORTED_EXTENSIONS,
    extract_text,
    is_supported,
)


def _make_pdf(path, text):
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawString(72, 720, text)
    c.save()


def _make_docx(path, paragraphs):
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(str(path))


def test_supported_extensions_include_pdf_doc_and_docx():
    assert ".pdf" in SUPPORTED_EXTENSIONS
    assert ".docx" in SUPPORTED_EXTENSIONS
    assert ".doc" in SUPPORTED_EXTENSIONS


def test_is_supported_is_case_insensitive():
    assert is_supported("Resume.PDF")
    assert is_supported("resume.DOCX")
    assert is_supported("resume.DOC")
    assert not is_supported("resume.txt")
    assert not is_supported("resume.pages")
    assert not is_supported("resume")


def test_decode_doc_bytes_reads_utf16():
    from utils.parser import _decode_doc_bytes
    raw = "Python Django Flask AWS PostgreSQL resume content".encode("utf-16-le")
    out = _decode_doc_bytes(raw)
    assert "Python" in out and "Django" in out and "PostgreSQL" in out


def test_decode_doc_bytes_reads_cp1252():
    from utils.parser import _decode_doc_bytes
    raw = "Senior Python developer with Flask experience".encode("cp1252")
    out = _decode_doc_bytes(raw)
    assert "Python developer" in out


def test_extract_text_from_doc_rejects_non_ole(tmp_path):
    from utils.parser import extract_text_from_doc
    bad = tmp_path / "fake.doc"
    bad.write_bytes(b"this is not an OLE compound file")
    with pytest.raises(ValueError):
        extract_text_from_doc(str(bad))


def test_extract_text_from_doc_reads_word_stream(monkeypatch):
    """Full .doc path: read WordDocument stream, decode, return text."""
    from types import SimpleNamespace
    import utils.parser as parser

    text = (
        "Senior Python developer skilled in Django, Flask, AWS, Docker, "
        "PostgreSQL, Git and REST APIs, with five years building scalable "
        "backend services and Kubernetes deployments."
    )
    raw = text.encode("utf-16-le")

    class FakeOle:
        def exists(self, name):
            return name == "WordDocument"

        def openstream(self, name):
            return SimpleNamespace(read=lambda: raw)

        def close(self):
            pass

    monkeypatch.setattr(parser.olefile, "isOleFile", lambda p: True)
    monkeypatch.setattr(parser.olefile, "OleFileIO", lambda p: FakeOle())

    out = parser.extract_text_from_doc("resume.doc")
    assert "Python" in out and "Django" in out and "Kubernetes" in out


def test_extract_text_from_doc_raises_on_garbage_stream(monkeypatch):
    """A stream with no real words is rejected (caller shows a friendly message)."""
    from types import SimpleNamespace
    import utils.parser as parser

    class FakeOle:
        def exists(self, name):
            return name == "WordDocument"

        def openstream(self, name):
            return SimpleNamespace(read=lambda: bytes(range(0, 31)) * 20)

        def close(self):
            pass

    monkeypatch.setattr(parser.olefile, "isOleFile", lambda p: True)
    monkeypatch.setattr(parser.olefile, "OleFileIO", lambda p: FakeOle())

    with pytest.raises(ValueError):
        parser.extract_text_from_doc("resume.doc")


def test_extract_text_reads_pdf(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, "Python developer with Django")
    text = extract_text(str(pdf))
    assert "Python developer with Django" in text


def test_extract_text_reads_docx(tmp_path):
    docx_path = tmp_path / "r.docx"
    _make_docx(docx_path, ["Jane Doe", "Skilled in Python, Flask and AWS."])
    text = extract_text(str(docx_path))
    assert "Jane Doe" in text
    assert "Flask" in text


def test_extract_text_dispatches_by_extension_case_insensitively(tmp_path):
    docx_path = tmp_path / "R.DOCX"
    _make_docx(docx_path, ["Kubernetes and Terraform expert"])
    assert "Kubernetes" in extract_text(str(docx_path))


def test_extract_text_unsupported_type_raises(tmp_path):
    bad = tmp_path / "r.txt"
    bad.write_text("hello world")
    with pytest.raises(ValueError):
        extract_text(str(bad))


# --------------------------------------------------------------------------- #
# In-memory extraction (no temp files, serverless-friendly)
# --------------------------------------------------------------------------- #
def test_extract_text_from_bytes_pdf(tmp_path):
    from utils.parser import extract_text_from_bytes
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, "Python developer with Django")
    text = extract_text_from_bytes(pdf.read_bytes(), "resume.pdf")
    assert "Python developer with Django" in text


def test_extract_text_from_bytes_docx(tmp_path):
    from utils.parser import extract_text_from_bytes
    docx_path = tmp_path / "r.docx"
    _make_docx(docx_path, ["Jane Doe", "Skilled in Python, Flask and AWS."])
    text = extract_text_from_bytes(docx_path.read_bytes(), "resume.docx")
    assert "Jane Doe" in text
    assert "Flask" in text


def test_extract_text_from_bytes_doc(monkeypatch):
    from types import SimpleNamespace
    import utils.parser as parser

    text = (
        "Senior Python developer skilled in Django, Flask, AWS, Docker, "
        "PostgreSQL, Git and REST APIs, with five years building scalable "
        "backend services and Kubernetes deployments."
    )
    raw = text.encode("utf-16-le")

    class FakeOle:
        def exists(self, name):
            return name == "WordDocument"

        def openstream(self, name):
            return SimpleNamespace(read=lambda: raw)

        def close(self):
            pass

    monkeypatch.setattr(parser.olefile, "isOleFile", lambda src: True)
    monkeypatch.setattr(parser.olefile, "OleFileIO", lambda src: FakeOle())

    out = parser.extract_text_from_bytes(b"fake-ole-bytes", "resume.doc")
    assert "Python" in out and "Django" in out


def test_extract_text_from_bytes_unsupported_raises():
    from utils.parser import extract_text_from_bytes
    with pytest.raises(ValueError):
        extract_text_from_bytes(b"hello", "resume.txt")
