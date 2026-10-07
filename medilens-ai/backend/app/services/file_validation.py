"""Pure helpers for validating uploads. No I/O, no framework dependencies."""
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Optional

from app.core.errors import InvalidUploadError, UnsupportedFileTypeError

# MIME type -> extensions allowed for that type
ALLOWED_TYPES = {
    "application/pdf": (".pdf",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
}
ALLOWED_EXTENSIONS = frozenset(ext for exts in ALLOWED_TYPES.values() for ext in exts)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_PDF_SIGNATURE = b"%PDF-"

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_STEM_LENGTH = 100
_FALLBACK_STEM = "report"


def basename_of(filename: str) -> str:
    """Strip any directory part (both / and \\ styles) and control characters."""
    name = filename.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32 and ord(ch) != 127)
    return name.strip()


def display_filename(filename: str) -> str:
    """Client's filename, path-stripped. Safe to return as metadata only."""
    return basename_of(filename)[:255]


def normalize_content_type(content_type: Optional[str]) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def get_extension(filename: str) -> str:
    return PurePosixPath(basename_of(filename)).suffix.lower()


def detect_content_type(header: bytes) -> Optional[str]:
    """Identify the real file type from its leading bytes (magic numbers)."""
    if header.startswith(_PDF_SIGNATURE):
        return "application/pdf"
    if header.startswith(_JPEG_SIGNATURE):
        return "image/jpeg"
    if header.startswith(_PNG_SIGNATURE):
        return "image/png"
    return None


def validate_declared_type(filename: str, content_type: Optional[str]) -> tuple[str, str]:
    """Check extension and client-declared MIME type. Returns (extension, mime)."""
    ext = get_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file extension. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    mime = normalize_content_type(content_type)
    if mime not in ALLOWED_TYPES:
        raise UnsupportedFileTypeError(
            "Unsupported content type. Allowed: application/pdf, image/jpeg, image/png."
        )
    return ext, mime


def validate_content_matches(header: bytes, ext: str, declared_mime: str) -> str:
    """Verify the real content agrees with the extension and declared MIME type.

    Returns the detected (trusted) MIME type.
    """
    detected = detect_content_type(header)
    if detected is None:
        raise UnsupportedFileTypeError(
            "File content is not a supported type (PDF, JPEG or PNG)."
        )
    if detected != declared_mime or ext not in ALLOWED_TYPES[detected]:
        raise InvalidUploadError(
            "File content does not match its extension or declared content type."
        )
    return detected


def sanitize_filename(filename: str, ext: str) -> str:
    """Build a filesystem-safe name: [A-Za-z0-9._-] only, no separators or dots-prefix.

    The extension is supplied by the caller (already validated), not parsed again.
    """
    base = basename_of(filename)
    stem = base[: -len(ext)] if ext and base.lower().endswith(ext) else base
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    stem = re.sub(r"\.{2,}", ".", stem)  # no ".." sequences, even though separators are gone
    stem = stem.strip("._-")[:_MAX_STEM_LENGTH].strip("._-")
    if not stem:
        stem = _FALLBACK_STEM
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    return f"{stem}{ext}"
