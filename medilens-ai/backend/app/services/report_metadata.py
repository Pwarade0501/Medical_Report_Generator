"""Small local SQLite index for uploaded-report history (no report content)."""
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.models.schemas import ReportHistoryItem

logger = logging.getLogger("medilens.report_metadata")
DB_NAME = ".report_metadata.sqlite3"


class ReportMetadataStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.database = self.root / DB_NAME

    def _connect(self):
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=5)
        connection.execute("""CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY, filename TEXT NOT NULL, file_type TEXT NOT NULL,
            uploaded_at TEXT NOT NULL, status TEXT NOT NULL)""")
        return connection

    def record_upload(self, report_id: UUID, filename: str, file_type: str) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO reports VALUES (?, ?, ?, ?, ?)", (
                str(report_id), filename, file_type,
                datetime.now(timezone.utc).isoformat(), "uploaded"))

    def list_reports(self) -> list[ReportHistoryItem]:
        records = {}
        try:
            with self._connect() as db:
                rows = db.execute("SELECT report_id, filename, file_type, uploaded_at, status "
                                   "FROM reports ORDER BY uploaded_at DESC").fetchall()
            for report_id, filename, file_type, uploaded_at, status in rows:
                try:
                    parsed_id = UUID(report_id)
                    report_path = self.root / str(parsed_id)
                    files = [p for p in report_path.iterdir() if p.is_file()]
                    if len(files) != 1:
                        continue
                    records[report_id] = ReportHistoryItem(
                        report_id=parsed_id, filename=filename, file_type=file_type,
                        uploaded_at=datetime.fromisoformat(uploaded_at), status=status)
                except (OSError, ValueError):
                    continue
        except sqlite3.Error as exc:
            logger.warning("Report history metadata unavailable (%s)", type(exc).__name__)

        # Include reports created before the metadata index existed without inventing a date.
        try:
            for folder in self.root.iterdir():
                if not folder.is_dir():
                    continue
                try:
                    report_id = UUID(folder.name)
                    if str(report_id) in records:
                        continue
                    files = [p for p in folder.iterdir() if p.is_file()]
                    if len(files) != 1 or files[0].suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
                        continue
                    extension = files[0].suffix.lower()
                    mime = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}[extension]
                    records[str(report_id)] = ReportHistoryItem(
                        report_id=report_id, filename=files[0].name, file_type=mime, uploaded_at=None)
                except (OSError, ValueError):
                    continue
        except OSError as exc:
            logger.warning("Report history storage unavailable (%s)", type(exc).__name__)
        return sorted(records.values(), key=lambda item: item.uploaded_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
