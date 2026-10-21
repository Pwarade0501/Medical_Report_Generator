"""Local development storage for uploaded reports.

Layout:  <root>/<report_id>/<sanitized_filename>

All path decisions are made here; user input never becomes a path directly.
"""
import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import (ApiError, EmptyFileError, FileTooLargeError,
                             ReportNotFoundError, StorageError, UnsupportedReportError)
from app.services import file_validation as fv
from app.services.report_metadata import ReportMetadataStore

logger = logging.getLogger("medilens.storage")

CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class StoredReport:
    report_id: uuid.UUID
    original_filename: str  # metadata only, path-stripped
    stored_filename: str  # sanitized, what is on disk
    file_type: str
    file_size: int
    path: Path  # internal use only (e.g. later phases); never returned by the API


class ReportStorage:
    def __init__(self, root: Path, max_upload_bytes: int):
        self.root = Path(root).resolve()
        self.max_upload_bytes = max_upload_bytes

    def _max_size_label(self) -> str:
        return f"{self.max_upload_bytes / (1024 * 1024):g} MB"

    def get_report_path(self, report_id: uuid.UUID) -> Path:
        """Resolve a supported uploaded report by its server-generated ID."""
        report_dir = (self.root / str(report_id)).resolve()
        if report_dir.parent != self.root:
            raise ReportNotFoundError("Report not found.")
        try:
            candidates = [p for p in report_dir.iterdir() if p.is_file()]
        except FileNotFoundError:
            raise ReportNotFoundError("Report not found.")
        except OSError:
            logger.exception("Failed to locate report %s", report_id)
            raise StorageError("Failed to access the uploaded report.")
        if not candidates:
            raise ReportNotFoundError("Report not found.")
        if len(candidates) != 1 or candidates[0].suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
            raise UnsupportedReportError("Text extraction supports PDF, JPG, JPEG and PNG reports.")
        return candidates[0]

    async def save_report(self, upload: UploadFile) -> StoredReport:
        # 1. Cheap checks first: extension + declared MIME type
        filename = upload.filename or ""
        ext, declared_mime = fv.validate_declared_type(filename, upload.content_type)

        # 2. Look at the real content before writing anything
        first_chunk = await upload.read(CHUNK_SIZE)
        if not first_chunk:
            raise EmptyFileError("The uploaded file is empty.")
        file_type = fv.validate_content_matches(first_chunk, ext, declared_mime)

        # 3. App-controlled location: unique UUID directory + sanitized name
        report_id = uuid.uuid4()
        stored_name = fv.sanitize_filename(filename, ext)
        report_dir = self.root / str(report_id)
        file_path = report_dir / stored_name
        if file_path.resolve().parent != report_dir.resolve() or report_dir.resolve().parent != self.root:
            # Defensive: should be impossible after sanitizing.
            raise StorageError("Failed to store the uploaded file.")

        # 4. Stream to disk, enforcing the size limit as we go
        size = 0
        try:
            report_dir.mkdir(parents=True, exist_ok=False)
            with open(file_path, "xb") as out:  # "x": never overwrite
                chunk = first_chunk
                while chunk:
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise FileTooLargeError(
                            f"File too large. Maximum allowed size is {self._max_size_label()}."
                        )
                    out.write(chunk)
                    chunk = await upload.read(CHUNK_SIZE)
        except ApiError:
            shutil.rmtree(report_dir, ignore_errors=True)
            raise
        except OSError:
            logger.exception("Failed to store report %s", report_id)
            shutil.rmtree(report_dir, ignore_errors=True)
            raise StorageError("Failed to store the uploaded file.")

        try:
            ReportMetadataStore(self.root).record_upload(
                report_id, fv.display_filename(filename), file_type
            )
        except Exception as exc:
            logger.error("Failed to index report %s (%s)", report_id, type(exc).__name__)
            shutil.rmtree(report_dir, ignore_errors=True)
            raise StorageError("Failed to store the uploaded file.") from exc

        return StoredReport(
            report_id=report_id,
            original_filename=fv.display_filename(filename),
            stored_filename=stored_name,
            file_type=file_type,
            file_size=size,
            path=file_path,
        )


def get_report_storage() -> ReportStorage:
    """FastAPI dependency. Tests override this to use a temp directory."""
    return ReportStorage(
        root=settings.report_storage_dir,
        max_upload_bytes=settings.max_upload_size_bytes,
    )
