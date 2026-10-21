from datetime import date
from uuid import uuid4

import pytest

from app.core.errors import PdfExtractionError
from app.models.schemas import ReportTextExtractionResponse
from app.services.structured_extraction import extract_structured_data


def parse(text):
    return extract_structured_data(uuid4(), text)


def test_extracts_multiple_labs_values_units_ranges_and_report_date():
    result = parse(
        "Report Date: 2025-04-03\n"
        "Hemoglobin 13.4 g/dL Reference Range: 12.0 - 16.0\n"
        "Glucose 105 mg/dL 70 - 99 H\n"
        "TSH 2.1 mIU/L 0.4 - 4.0"
    )

    assert result.report_date == date(2025, 4, 3)
    assert result.result_count == 3
    assert [r.test_name for r in result.results] == ["Hemoglobin", "Glucose", "TSH"]
    assert [(r.value, r.unit, r.reference_range) for r in result.results] == [
        ("13.4", "g/dL", "Reference Range: 12.0 - 16.0"),
        ("105", "mg/dL", "70 - 99"),
        ("2.1", "mIU/L", "0.4 - 4.0"),
    ]
    assert result.results[1].flag == "high"
    assert result.results[0].source_text == "Hemoglobin 13.4 g/dL Reference Range: 12.0 - 16.0"


def test_missing_unit_and_reference_range_remain_null():
    result = parse("Hemoglobin 13.4")
    item = result.results[0]
    assert item.value == "13.4"
    assert item.unit is None
    assert item.reference_range is None


def test_decimal_and_negative_values_are_preserved_as_reported():
    result = parse("Sodium -1.25 mmol/L -2.0 to 2.0")
    item = result.results[0]
    assert item.value == "-1.25"
    assert item.unit == "mmol/L"
    assert item.reference_range == "-2.0 to 2.0"


def test_textual_result_is_preserved_without_inventing_a_unit():
    item = parse("CRP Positive").results[0]
    assert item.value == "Positive"
    assert item.unit is None
    assert item.flag is None


def test_explicit_high_and_low_flags_are_normalized_but_not_inferred():
    result = parse("Glucose 105 mg/dL H\nPotassium 3.2 mmol/L low\nSodium 140 mmol/L")
    assert [item.flag for item in result.results] == ["high", "low", None]


def test_missing_or_ambiguous_value_is_partial_and_marked_for_review():
    result = parse("Glucose result unavailable")
    assert result.result_count == 1
    assert result.results[0].value is None
    assert result.results[0].needs_review is True
    assert result.warnings[0].code == "ambiguous_result"


def test_ocr_damaged_test_name_is_warned_about_not_guessed():
    result = parse("Gluc0se 1O5 mg/dL")
    assert result.result_count == 0
    assert result.warnings[0].code == "unrecognized_lab_name"
    assert "not guessed" in result.warnings[0].message


def test_ambiguous_numeric_date_is_not_assigned():
    result = parse("Report Date: 03/04/2025\nGlucose 90 mg/dL")
    assert result.report_date is None
    assert result.results[0].date is None
    assert any(w.code == "ambiguous_date" for w in result.warnings)


def test_unrelated_numbers_are_not_reported_as_labs():
    result = parse(
        "Patient ID: 123456789\nPhone: +1 555 123 4567\n"
        "Page 2 of 4\nInvoice number 778899"
    )
    assert result.result_count == 0
    assert result.results == []


def test_empty_extracted_text_uses_project_error_convention():
    with pytest.raises(PdfExtractionError) as exc:
        parse(" \n ")
    assert exc.value.status_code == 422
    assert exc.value.detail == "No extracted report text is available to structure."


def test_endpoint_reuses_existing_extraction_pipeline(client, monkeypatch):
    import app.routers.reports as reports_router

    report_id = uuid4()
    extracted = ReportTextExtractionResponse(
        report_id=report_id,
        extracted_text="Hemoglobin 13.2 g/dL",
        page_count=1,
        pages_with_text=1,
        character_count=len("Hemoglobin 13.2 g/dL"),
        extraction_method="embedded_text",
    )
    monkeypatch.setattr(reports_router, "extract_report_text", lambda given_id, storage: extracted)
    response = client.post(f"/api/v1/reports/{report_id}/extract-structured-data")

    assert response.status_code == 200
    body = response.json()
    assert body["report_id"] == str(report_id)
    assert body["result_count"] == 1
    assert body["results"][0]["test_name"] == "Hemoglobin"
    assert body["results"][0]["value"] == "13.2"


def test_missing_report_id_returns_404(client):
    response = client.post("/api/v1/reports/00000000-0000-4000-8000-000000000000/extract-structured-data")
    assert response.status_code == 404


def test_empty_text_from_pipeline_returns_422(client, monkeypatch):
    import app.routers.reports as reports_router

    report_id = uuid4()
    extracted = ReportTextExtractionResponse(
        report_id=report_id, extracted_text="", page_count=1, pages_with_text=1,
        character_count=0, extraction_method="embedded_text",
    )
    monkeypatch.setattr(reports_router, "extract_report_text", lambda given_id, storage: extracted)
    response = client.post(f"/api/v1/reports/{report_id}/extract-structured-data")
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "No extracted report text is available to structure."
