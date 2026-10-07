import pytest

from app.services.file_validation import (
    basename_of,
    detect_content_type,
    sanitize_filename,
)
from tests.helpers import JPEG_BYTES, PDF_BYTES, PNG_BYTES


@pytest.mark.parametrize(
    "raw,ext,expected",
    [
        ("report.pdf", ".pdf", "report.pdf"),
        ("../../etc/passwd.pdf", ".pdf", "passwd.pdf"),
        ("..\\..\\x.pdf", ".pdf", "x.pdf"),
        ("my report (final).pdf", ".pdf", "my_report_final.pdf"),
        ("...hidden.pdf", ".pdf", "hidden.pdf"),
        ("a..b.pdf", ".pdf", "a.b.pdf"),
        ("नमस्ते.pdf", ".pdf", "report.pdf"),  # nothing ASCII left -> fallback
        (".pdf", ".pdf", "report.pdf"),
        ("CON.pdf", ".pdf", "_CON.pdf"),  # Windows reserved device name
        ("nul.png", ".png", "_nul.png"),
        ("bad\x00name.pdf", ".pdf", "badname.pdf"),  # control chars removed
        ("UPPER.PDF", ".pdf", "UPPER.pdf"),
    ],
)
def test_sanitize_filename(raw, ext, expected):
    assert sanitize_filename(raw, ext) == expected


def test_sanitize_filename_truncates_long_names():
    result = sanitize_filename("a" * 500 + ".pdf", ".pdf")
    assert result == "a" * 100 + ".pdf"


def test_basename_of_handles_both_separators():
    assert basename_of("/abs/path/file.pdf") == "file.pdf"
    assert basename_of("C:\\dir\\file.pdf") == "file.pdf"


def test_detect_content_type():
    assert detect_content_type(PDF_BYTES) == "application/pdf"
    assert detect_content_type(PNG_BYTES) == "image/png"
    assert detect_content_type(JPEG_BYTES) == "image/jpeg"
    assert detect_content_type(b"plain text") is None
    assert detect_content_type(b"") is None
