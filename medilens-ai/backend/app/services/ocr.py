"""Local Tesseract OCR adapters with bounded image and execution resources."""
import logging
import subprocess
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps
from pytesseract import TesseractNotFoundError
from pytesseract import TesseractError

from app.core.config import settings
from app.core.errors import OcrProcessingError, OcrResourceLimitError, OcrUnavailableError

logger = logging.getLogger("medilens.ocr")

MAX_IMAGE_DIMENSION = 10_000
MAX_IMAGE_PIXELS = 40_000_000
MAX_PDF_PAGES = 50
OCR_TIMEOUT_SECONDS = 30
MAX_OCR_PROCESSING_SECONDS = 120
PDF_RENDER_SCALE = 2.0


def _configure_engine() -> None:
    if settings.TESSERACT_CMD.strip():
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD.strip()


def _check_dimensions(width: int, height: int) -> None:
    if (width <= 0 or height <= 0 or width > MAX_IMAGE_DIMENSION
            or height > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS):
        raise OcrResourceLimitError("Image dimensions exceed the OCR processing limit.")


def _recognize(image: Image.Image, timeout_seconds: float = OCR_TIMEOUT_SECONDS) -> str:
    _configure_engine()
    try:
        return pytesseract.image_to_string(image, timeout=timeout_seconds).strip()
    except TesseractNotFoundError as exc:
        raise OcrUnavailableError(
            "Tesseract OCR is not installed or not on PATH. Install Tesseract and restart the backend."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise OcrResourceLimitError("OCR exceeded the 30-second processing limit.") from exc
    except RuntimeError as exc:
        if "timeout" in str(exc).lower():
            raise OcrResourceLimitError("OCR exceeded the 30-second processing limit.") from exc
        logger.warning("Tesseract failed (%s)", type(exc).__name__)
        raise OcrProcessingError("OCR could not read this report.") from exc
    except TesseractError as exc:
        logger.warning("Tesseract failed (%s)", type(exc).__name__)
        raise OcrProcessingError("OCR could not read this report.") from exc
    except OcrUnavailableError:
        raise
    except Exception as exc:
        logger.warning("OCR failed (%s)", type(exc).__name__)
        raise OcrProcessingError("OCR could not read this report.") from exc


def recognize_image(path: Path) -> str:
    """OCR a stored JPG/JPEG/PNG without loading oversized images into memory."""
    try:
        with Image.open(path) as source:
            _check_dimensions(*source.size)
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except OcrResourceLimitError:
        raise
    except Exception as exc:
        logger.info("Unreadable image (%s)", type(exc).__name__)
        raise OcrProcessingError("The uploaded image is unreadable or damaged.") from exc
    text = _recognize(image)
    if not text.strip():
        raise OcrProcessingError("OCR found no readable text in this image.")
    return text


def recognize_pdf_page(page, timeout_seconds: float = OCR_TIMEOUT_SECONDS) -> str:
    """Render one PDF page within pixel limits, then pass it to Tesseract."""
    try:
        width_pt, height_pt = page.get_size()
        scale = min(PDF_RENDER_SCALE, MAX_IMAGE_DIMENSION / max(width_pt, height_pt))
        width_px, height_px = int(width_pt * scale), int(height_pt * scale)
        _check_dimensions(width_px, height_px)
        bitmap = page.render(scale=scale)
        try:
            image = bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
    except OcrResourceLimitError:
        raise
    except Exception as exc:
        logger.info("PDF page could not be rendered (%s)", type(exc).__name__)
        raise OcrProcessingError("A PDF page could not be rendered for OCR.") from exc
    return _recognize(image, timeout_seconds=timeout_seconds)
