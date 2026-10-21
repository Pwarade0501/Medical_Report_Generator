"""Pydantic request/response models."""
from datetime import date as Date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ReportUploadResponse(BaseModel):
    report_id: UUID = Field(description="Server-generated unique report ID (UUID4)")
    filename: str = Field(description="Original filename as sent by the client (metadata only)")
    file_type: str = Field(description="Detected content type, e.g. application/pdf")
    file_size: int = Field(description="Size in bytes")
    status: Literal["uploaded"] = "uploaded"


class ReportHistoryItem(BaseModel):
    report_id: UUID
    filename: str | None = None
    uploaded_at: datetime | None = None
    file_type: str | None = None
    status: Literal["uploaded"] = "uploaded"


class ReportHistoryResponse(BaseModel):
    reports: list[ReportHistoryItem]
    count: int


class ReportComparisonRequest(BaseModel):
    previous_report_id: UUID
    current_report_id: UUID


class ComparedTest(BaseModel):
    test_name: str
    previous_value: str | None = None
    previous_unit: str | None = None
    previous_reference_range: str | None = None
    current_value: str | None = None
    current_unit: str | None = None
    current_reference_range: str | None = None
    difference: str | None = None
    status: Literal["comparable", "missing_value", "ambiguous_value", "unit_mismatch", "missing_unit"]


class ReportComparisonResponse(BaseModel):
    previous_report_id: UUID
    current_report_id: UUID
    previous_report_date: Date | None = None
    current_report_date: Date | None = None
    comparisons: list[ComparedTest]
    missing_from_previous: list[str]
    missing_from_current: list[str]
    note: str
    disclaimer: str


class ReportTextExtractionResponse(BaseModel):
    report_id: UUID
    extracted_text: str
    page_count: int = Field(ge=0)
    pages_with_text: int = Field(ge=0)
    character_count: int = Field(ge=0)
    extraction_method: Literal["embedded_text", "ocr", "mixed"]
    status: Literal["extracted"] = "extracted"


class StructuredLabResult(BaseModel):
    test_name: str
    value: str | None = None
    unit: str | None = None
    reference_range: str | None = None
    date: Date | None = None
    flag: Literal["high", "low", "normal"] | None = None
    source_text: str
    needs_review: bool = False


class StructuredExtractionWarning(BaseModel):
    line_number: int = Field(ge=1)
    code: Literal["ambiguous_result", "unrecognized_lab_name", "ambiguous_date"]
    message: str
    source_text: str


class StructuredReportResponse(BaseModel):
    report_id: UUID
    report_date: Date | None = None
    result_count: int = Field(ge=0)
    results: list[StructuredLabResult]
    warnings: list[StructuredExtractionWarning] = Field(default_factory=list)
    status: Literal["extracted"] = "extracted"


class AIResultExplanationDraft(BaseModel):
    result_index: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=700)


class AIExplanationDraft(BaseModel):
    summary: str = Field(min_length=1, max_length=1000)
    result_explanations: list[AIResultExplanationDraft]
    questions_for_doctor: list[str] = Field(min_length=1, max_length=5)


class ReportResultExplanation(BaseModel):
    test_name: str
    reported_value: str | None
    unit: str | None
    reference_range: str | None
    printed_flag: Literal["high", "low", "normal"] | None
    range_comparison: Literal["within_range", "outside_range", "not_comparable"]
    explanation: str
    needs_review: bool


class ReportExplanationResponse(BaseModel):
    report_id: UUID
    report_date: Date | None = None
    language: Literal["en", "hi", "mr"]
    summary: str
    result_explanations: list[ReportResultExplanation]
    questions_for_doctor: list[str]
    warnings: list[str]
    comparison_note: str
    disclaimer: str
    provider: Literal["openai"] = "openai"
    generation_method: Literal["openai_responses"] = "openai_responses"
    status: Literal["explained"] = "explained"
