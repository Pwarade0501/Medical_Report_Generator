"""Embedded PDF text extraction with local OCR fallback for scanned pages."""
import logging
import time
import uuid

import pypdfium2 as pdfium
from pypdf import PdfReader

from app.core.errors import PdfExtractionError
from app.core.config import settings
from app.core.errors import OcrProcessingError, OcrResourceLimitError
from app.models.schemas import ReportTextExtractionResponse
from app.services.storage import ReportStorage
from app.services.ocr import (MAX_OCR_PROCESSING_SECONDS, MAX_PDF_PAGES,
                              OCR_TIMEOUT_SECONDS, recognize_image, recognize_pdf_page)

logger = logging.getLogger("medilens.pdf_extraction")


def extract_report_text(report_id: uuid.UUID, storage: ReportStorage) -> ReportTextExtractionResponse:
    path = storage.get_report_path(report_id)
    if path.stat().st_size > settings.max_upload_size_bytes:
        raise OcrResourceLimitError("Report exceeds the configured processing size limit.")
    if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        text = recognize_image(path)
        return _response(report_id, text, 1, 1, "ocr")

    try:
        reader = PdfReader(str(path), strict=False)
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            raise OcrResourceLimitError(f"PDF exceeds the {MAX_PDF_PAGES}-page processing limit.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        if hasattr(exc, "status_code"):
            raise
        logger.warning("PDF extraction failed for report %s (%s)", report_id, type(exc).__name__)
        raise PdfExtractionError("Could not extract text from this PDF.") from exc

    if not page_count:
        raise PdfExtractionError("The PDF contains no pages to extract.")

    method = "embedded_text"
    if any(not text.strip() for text in pages):
        embedded_pages = [bool(text.strip()) for text in pages]
        deadline = time.monotonic() + MAX_OCR_PROCESSING_SECONDS
        try:
            document = pdfium.PdfDocument(str(path))
            try:
                for index, text in enumerate(pages):
                    if not text.strip():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise OcrResourceLimitError(
                                f"PDF OCR exceeded the {MAX_OCR_PROCESSING_SECONDS}-second processing limit."
                            )
                        page = document[index]
                        try:
                            pages[index] = recognize_pdf_page(
                                page, timeout_seconds=min(OCR_TIMEOUT_SECONDS, remaining)
                            )
                        finally:
                            page.close()
            finally:
                document.close()
        except Exception as exc:
            if hasattr(exc, "status_code"):
                raise
            logger.warning("PDF OCR fallback failed for report %s (%s)", report_id, type(exc).__name__)
            raise OcrProcessingError("Could not process every PDF page for OCR.") from exc
        method = "mixed" if any(embedded_pages) else "ocr"

    pages_with_text = sum(bool(text.strip()) for text in pages)
    if not pages_with_text:
        raise OcrProcessingError("OCR found no readable text in this PDF.")
    return _response(report_id, "\n\n".join(text.strip() for text in pages),
                     page_count, pages_with_text, method)


def _response(report_id: uuid.UUID, text: str, page_count: int,
              pages_with_text: int, method: str) -> ReportTextExtractionResponse:
    return ReportTextExtractionResponse(
        report_id=report_id,
        extracted_text=text,
        page_count=page_count,
        pages_with_text=pages_with_text,
        character_count=len(text),
        extraction_method=method,
    )
