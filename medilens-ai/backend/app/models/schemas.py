"""Pydantic request/response models."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ReportUploadResponse(BaseModel):
    report_id: UUID = Field(description="Server-generated unique report ID (UUID4)")
    filename: str = Field(description="Original filename as sent by the client (metadata only)")
    file_type: str = Field(description="Detected content type, e.g. application/pdf")
    file_size: int = Field(description="Size in bytes")
    status: Literal["uploaded"] = "uploaded"
