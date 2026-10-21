"""Report upload router (thin: validation and storage live in services)."""
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.models.schemas import (ReportTextExtractionResponse, ReportUploadResponse,
                                StructuredReportResponse)
from app.models.schemas import ReportExplanationResponse
from app.models.schemas import (ReportComparisonRequest, ReportComparisonResponse,
                                ReportHistoryResponse)
from app.services.explanation import explain_structured_report
from app.services.comparison import compare_reports
from app.services.pdf_extraction import extract_report_text
from app.services.report_metadata import ReportMetadataStore
from app.services.storage import ReportStorage, get_report_storage
from app.services.structured_extraction import extract_structured_data

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ReportHistoryResponse, summary="List uploaded report history")
def report_history(storage: ReportStorage = Depends(get_report_storage)) -> ReportHistoryResponse:
    reports = ReportMetadataStore(storage.root).list_reports()
    return ReportHistoryResponse(reports=reports, count=len(reports))


@router.post("/compare", response_model=ReportComparisonResponse,
             summary="Compare structured results from two uploaded reports",
             responses={400: {"description": "Report IDs must be different"},
                        404: {"description": "Report not found"},
                        415: {"description": "Unsupported report"},
                        422: {"description": "Report text could not be extracted"},
                        503: {"description": "OCR engine unavailable"}})
def compare_report_results(request: ReportComparisonRequest,
                           storage: ReportStorage = Depends(get_report_storage)) -> ReportComparisonResponse:
    return compare_reports(request.previous_report_id, request.current_report_id, storage)


@router.post(
    "/upload",
    response_model=ReportUploadResponse,
    status_code=201,
    summary="Upload a medical report (PDF, JPG, JPEG, PNG)",
    responses={
        400: {"description": "Empty file, invalid upload, or content/type mismatch"},
        413: {"description": "File too large"},
        415: {"description": "Unsupported file type"},
        500: {"description": "Storage failure"},
    },
)
async def upload_report(
    file: UploadFile = File(..., description="One report file"),
    storage: ReportStorage = Depends(get_report_storage),
) -> ReportUploadResponse:
    stored = await storage.save_report(file)
    return ReportUploadResponse(
        report_id=stored.report_id,
        filename=stored.original_filename,
        file_type=stored.file_type,
        file_size=stored.file_size,
        status="uploaded",
    )


@router.post(
    "/{report_id}/extract-text",
    response_model=ReportTextExtractionResponse,
    summary="Extract text from an uploaded PDF or image report (OCR fallback)",
    responses={404: {"description": "Report not found"}, 415: {"description": "Unsupported report"},
               422: {"description": "Report could not be read"}},
)
def extract_text(
    report_id: UUID,
    storage: ReportStorage = Depends(get_report_storage),
) -> ReportTextExtractionResponse:
    return extract_report_text(report_id, storage)


@router.post(
    "/{report_id}/extract-structured-data",
    response_model=StructuredReportResponse,
    summary="Extract supported laboratory results from an uploaded report",
    responses={404: {"description": "Report not found"}, 415: {"description": "Unsupported report"},
               422: {"description": "Report text could not be extracted or is empty"},
               503: {"description": "Local OCR engine is unavailable"}},
)
def extract_structured_report(
    report_id: UUID,
    storage: ReportStorage = Depends(get_report_storage),
) -> StructuredReportResponse:
    text_response = extract_report_text(report_id, storage)
    return extract_structured_data(report_id, text_response.extracted_text)


@router.post(
    "/{report_id}/explain",
    response_model=ReportExplanationResponse,
    summary="Generate a cautious educational explanation of a report",
    responses={404: {"description": "Report not found"}, 415: {"description": "Unsupported report"},
               422: {"description": "Report has no clear structured results"},
               413: {"description": "Too many structured results for one explanation request"},
               502: {"description": "AI provider failed or returned unusable output"},
               503: {"description": "AI provider is not configured"},
               504: {"description": "AI provider timed out"}},
)
def explain_report(
    report_id: UUID,
    language: Literal["en", "hi", "mr"] = Query(default="en"),
    storage: ReportStorage = Depends(get_report_storage),
) -> ReportExplanationResponse:
    text_response = extract_report_text(report_id, storage)
    structured = extract_structured_data(report_id, text_response.extracted_text)
    return explain_structured_report(report_id, structured, language)
