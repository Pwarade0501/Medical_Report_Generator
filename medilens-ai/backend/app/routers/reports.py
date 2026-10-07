"""Report upload router (thin: validation and storage live in services)."""
from fastapi import APIRouter, Depends, File, UploadFile

from app.models.schemas import ReportUploadResponse
from app.services.storage import ReportStorage, get_report_storage

router = APIRouter(prefix="/reports", tags=["reports"])


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
