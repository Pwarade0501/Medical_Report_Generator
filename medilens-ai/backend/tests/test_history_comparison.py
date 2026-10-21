"""Offline tests for local history and deterministic report comparison."""
from uuid import uuid4

import pytest

from tests.helpers import text_pdf_bytes

UPLOAD = "/api/v1/reports/upload"
HISTORY = "/api/v1/reports"
COMPARE = "/api/v1/reports/compare"


def upload(client, text, filename="report.pdf"):
    # Extraction fixtures remain tiny and synthetic; PDFs are valid for pypdf.
    return client.post(UPLOAD, files={"file": (filename, text_pdf_bytes(text), "application/pdf")})


@pytest.fixture(autouse=True)
def extraction_upload_limit(client):
    # The normal test storage limit is deliberately small for upload validation tests.
    from app.services.storage import get_report_storage
    client.app.dependency_overrides[get_report_storage]().max_upload_bytes = 8192


def test_history_empty(client):
    response = client.get(HISTORY)
    assert response.status_code == 200
    assert response.json() == {"reports": [], "count": 0}


def test_history_lists_multiple_uploads_without_paths_or_contents(client, storage_root):
    first = upload(client, "Hemoglobin 12.0 g/dL", "first.pdf").json()
    second = upload(client, "Glucose 95 mg/dL", "second.pdf").json()
    response = client.get(HISTORY)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    items = {item["report_id"]: item for item in body["reports"]}
    assert items[first["report_id"]]["filename"] == "first.pdf"
    assert items[second["report_id"]]["file_type"] == "application/pdf"
    assert items[first["report_id"]]["uploaded_at"]
    assert "path" not in response.text.lower()
    assert str(storage_root) not in response.text
    assert "Hemoglobin" not in response.text


def test_history_includes_legacy_report_without_inventing_timestamp(client, storage_root):
    from tests.helpers import PDF_BYTES
    from app.services.storage import get_report_storage
    storage = client.app.dependency_overrides[get_report_storage]()
    legacy_id = uuid4()
    folder = storage.root / str(legacy_id)
    folder.mkdir(parents=True)
    (folder / "old_report.pdf").write_bytes(PDF_BYTES)
    item = next(item for item in client.get(HISTORY).json()["reports"] if item["report_id"] == str(legacy_id))
    assert item["filename"] == "old_report.pdf"
    assert item["uploaded_at"] is None


def test_compare_valid_reports_and_calculate_difference(client):
    before = upload(client, "Hemoglobin 12.0 g/dL Reference Range 12.0 - 16.0").json()["report_id"]
    after = upload(client, "Hemoglobin 13.5 g/dL Reference Range 12.0 - 16.0").json()["report_id"]
    response = client.post(COMPARE, json={"previous_report_id": before, "current_report_id": after})
    assert response.status_code == 200
    body = response.json()
    assert body["comparisons"][0]["difference"] == "1.5"
    assert body["comparisons"][0]["status"] == "comparable"
    assert "clinical context" in body["note"]
    assert "diagnosis" in body["disclaimer"]


def test_compare_aliases_same_unit_and_reports_tests_missing_from_each(client):
    before = upload(client, "WBC 5.0 cells/uL\nGlucose 90 mg/dL").json()["report_id"]
    after = upload(client, "Leukocytes 6.0 cells/uL\nSodium 140 mmol/L").json()["report_id"]
    body = client.post(COMPARE, json={"previous_report_id": before, "current_report_id": after}).json()
    assert body["comparisons"][0]["difference"] == "1"
    assert body["missing_from_previous"] == ["Sodium"]
    assert body["missing_from_current"] == ["Glucose"]


def test_compare_incompatible_units_never_converts(client):
    before = upload(client, "Glucose 5.0 mmol/L").json()["report_id"]
    after = upload(client, "Glucose 90 mg/dL").json()["report_id"]
    result = client.post(COMPARE, json={"previous_report_id": before, "current_report_id": after}).json()["comparisons"][0]
    assert result["status"] == "unit_mismatch"
    assert result["difference"] is None


@pytest.mark.parametrize("line,status", [("Hemoglobin", "ambiguous_value"), ("Hemoglobin Positive g/dL", "ambiguous_value")])
def test_compare_ambiguous_or_missing_values_have_no_difference(client, line, status):
    before = upload(client, "Hemoglobin 12.0 g/dL").json()["report_id"]
    after = upload(client, line).json()["report_id"]
    result = client.post(COMPARE, json={"previous_report_id": before, "current_report_id": after}).json()["comparisons"][0]
    assert result["status"] == status
    assert result["difference"] is None


def test_compare_missing_id_returns_not_found(client):
    real = upload(client, "Hemoglobin 12 g/dL").json()["report_id"]
    response = client.post(COMPARE, json={"previous_report_id": str(uuid4()), "current_report_id": real})
    assert response.status_code == 404


def test_compare_same_report_and_malformed_requests(client):
    report_id = upload(client, "Hemoglobin 12 g/dL").json()["report_id"]
    assert client.post(COMPARE, json={"previous_report_id": report_id, "current_report_id": report_id}).status_code == 400
    assert client.post(COMPARE, json={"previous_report_id": "bad", "current_report_id": report_id}).status_code == 422
    assert client.post(COMPARE, json={"previous_report_id": report_id}).status_code == 422
