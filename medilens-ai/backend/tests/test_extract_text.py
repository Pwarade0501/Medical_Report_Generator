from io import BytesIO
from uuid import UUID

from pypdf import PdfWriter
import pytest

from tests.helpers import JPEG_BYTES, raster_text_image_bytes, scanned_pdf_bytes, text_pdf_bytes
from app.services.storage import get_report_storage

UPLOAD_URL = "/api/v1/reports/upload"


@pytest.fixture(autouse=True)
def allow_generated_pdf_size(client):
    # Generated pypdf files can exceed the upload suite's deliberately tiny limit.
    client.app.dependency_overrides[get_report_storage]().max_upload_bytes = 8192


def upload(client, filename, content, mime):
    return client.post(UPLOAD_URL, files={"file": (filename, content, mime)})


def test_extract_text_from_single_page_pdf(client):
    uploaded = upload(client, "report.pdf", text_pdf_bytes("Patient report"), "application/pdf")
    report_id = uploaded.json()["report_id"]
    response = client.post(f"/api/v1/reports/{report_id}/extract-text")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "report_id": report_id,
        "extracted_text": "Patient report",
        "page_count": 1,
        "pages_with_text": 1,
        "character_count": len("Patient report"),
        "extraction_method": "embedded_text",
        "status": "extracted",
    }


def test_extract_text_preserves_page_order_and_metadata(client):
    uploaded = upload(client, "multi.pdf", text_pdf_bytes("First page", "Second page"), "application/pdf")
    report_id = uploaded.json()["report_id"]
    response = client.post(f"/api/v1/reports/{report_id}/extract-text")

    assert response.status_code == 200
    body = response.json()
    assert body["extracted_text"] == "First page\n\nSecond page"
    assert body["page_count"] == 2
    assert body["pages_with_text"] == 2
    assert body["character_count"] == len(body["extracted_text"])
    assert body["extraction_method"] == "embedded_text"


def test_missing_report_returns_404(client):
    response = client.post("/api/v1/reports/00000000-0000-4000-8000-000000000000/extract-text")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Report not found."


def test_unreadable_image_returns_graceful_error(client):
    uploaded = upload(client, "photo.jpg", JPEG_BYTES, "image/jpeg")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")
    assert response.status_code == 422
    assert "unreadable" in response.json()["error"]["message"].lower()


def test_image_ocr_extracts_readable_text(client, monkeypatch):
    from app.services import ocr
    seen = []
    monkeypatch.setattr(ocr.pytesseract, "image_to_string", lambda image, timeout: seen.append(image.size) or "Hemoglobin 12.4")
    uploaded = upload(client, "report.png", raster_text_image_bytes("Hemoglobin 12.4"), "image/png")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")

    assert response.status_code == 200
    assert response.json()["extracted_text"] == "Hemoglobin 12.4"
    assert response.json()["extraction_method"] == "ocr"
    assert response.json()["page_count"] == 1
    assert seen == [(400, 100)]


def test_scanned_multipage_pdf_ocr_preserves_page_order(client, monkeypatch):
    from app.services import ocr
    outputs = iter(["Page one result", "Page two result"])
    monkeypatch.setattr(ocr.pytesseract, "image_to_string", lambda image, timeout: next(outputs))
    uploaded = upload(client, "scanned.pdf", scanned_pdf_bytes("page one", "page two"), "application/pdf")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extracted_text"] == "Page one result\n\nPage two result"
    assert body["page_count"] == 2
    assert body["pages_with_text"] == 2
    assert body["extraction_method"] == "ocr"


def test_missing_tesseract_returns_actionable_error(client, monkeypatch):
    import pytesseract
    from app.services import ocr
    def missing_engine(*args, **kwargs):
        raise pytesseract.TesseractNotFoundError()
    monkeypatch.setattr(ocr.pytesseract, "image_to_string", missing_engine)
    uploaded = upload(client, "report.png", raster_text_image_bytes("test text"), "image/png")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")

    assert response.status_code == 503
    assert "install tesseract" in response.json()["error"]["message"].lower()


def test_pdf_page_limit_rejected(client, monkeypatch):
    from app.services import pdf_extraction
    monkeypatch.setattr(pdf_extraction, "MAX_PDF_PAGES", 1)
    uploaded = upload(client, "scanned.pdf", scanned_pdf_bytes("one", "two"), "application/pdf")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")
    assert response.status_code == 413
    assert "page processing limit" in response.json()["error"]["message"].lower()


def test_ocr_engine_failure_is_reported_safely(client, monkeypatch):
    from app.services import ocr
    def failed(*args, **kwargs):
        raise RuntimeError("engine details should not reach the response")
    monkeypatch.setattr(ocr.pytesseract, "image_to_string", failed)
    uploaded = upload(client, "report.png", raster_text_image_bytes("test text"), "image/png")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")

    assert response.status_code == 422
    assert "engine details" not in response.text


def test_ocr_timeout_returns_resource_limit_error(client, monkeypatch):
    from app.services import ocr
    def timed_out(*args, **kwargs):
        raise RuntimeError("Tesseract process timeout")
    monkeypatch.setattr(ocr.pytesseract, "image_to_string", timed_out)
    uploaded = upload(client, "report.png", raster_text_image_bytes("test text"), "image/png")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")

    assert response.status_code == 413
    assert "30-second" in response.json()["error"]["message"]


def test_image_dimension_limit_rejected(client, monkeypatch):
    from app.services import ocr
    monkeypatch.setattr(ocr, "MAX_IMAGE_DIMENSION", 100)
    uploaded = upload(client, "large.png", raster_text_image_bytes("text"), "image/png")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")
    assert response.status_code == 413
    assert "dimensions" in response.json()["error"]["message"].lower()


def test_unsupported_extension_rejected_at_upload(client):
    response = upload(client, "report.gif", b"GIF89a", "image/gif")
    assert response.status_code == 415


def _pdf_bytes_without_pages():
    writer = PdfWriter()
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_empty_pdf_returns_graceful_error(client):
    uploaded = upload(client, "empty.pdf", _pdf_bytes_without_pages(), "application/pdf")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")
    assert response.status_code == 422
    assert "no pages" in response.json()["error"]["message"].lower()


def test_blank_pdf_without_text_returns_graceful_error(client, monkeypatch):
    from app.services import ocr
    monkeypatch.setattr(ocr.pytesseract, "image_to_string", lambda image, timeout: "")
    uploaded = upload(client, "scan.pdf", text_pdf_bytes("", "  "), "application/pdf")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")
    assert response.status_code == 422
    assert "no readable text" in response.json()["error"]["message"].lower()


def test_pdf_parse_failure_returns_safe_error(client):
    # The upload phase checks the signature; the extraction phase validates PDF structure.
    uploaded = upload(client, "broken.pdf", b"%PDF-not-a-real-pdf", "application/pdf")
    response = client.post(f"/api/v1/reports/{uploaded.json()['report_id']}/extract-text")
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Could not extract text from this PDF."


def test_invalid_report_id_returns_422(client):
    assert client.post("/api/v1/reports/not-a-uuid/extract-text").status_code == 422
