"""Deterministic, conservative comparison of structured report results."""
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.core.errors import InvalidUploadError, ReportNotFoundError
from app.models.schemas import ComparedTest, ReportComparisonResponse
from app.services.pdf_extraction import extract_report_text
from app.services.storage import ReportStorage
from app.services.structured_extraction import extract_structured_data

ALIASES = {
    "white blood cell count": "wbc", "white blood cells": "wbc", "leukocytes": "wbc",
    "red blood cell count": "rbc", "red blood cells": "rbc",
    "platelets": "platelet count", "sgpt": "alt", "alanine aminotransferase": "alt",
    "sgot": "ast", "aspartate aminotransferase": "ast", "glycated hemoglobin": "hba1c",
    "fasting blood sugar": "fbs", "blood urea nitrogen": "bun",
    "thyroid stimulating hormone": "tsh", "25 oh vitamin d": "vitamin d",
}
DISCLAIMER = "Educational information only. This is not a diagnosis or medical advice. Discuss reports with a qualified healthcare professional."
NOTE = "Numerical differences are arithmetic only. Changes may depend on laboratory methods, dates, and clinical context; direction alone does not mean improvement or worsening."


def _key(name: str) -> str:
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", name.casefold()).split())
    return ALIASES.get(normalized, normalized)


def _unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return re.sub(r"\s+", "", unit.casefold().replace("µ", "u").replace("μ", "u"))


def _number(value: str | None) -> Decimal | None:
    if not value or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value.strip()):
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def compare_reports(previous_id: UUID, current_id: UUID, storage: ReportStorage) -> ReportComparisonResponse:
    if previous_id == current_id:
        raise InvalidUploadError("Choose two different report IDs to compare.")
    # Check both files before running potentially expensive OCR.
    storage.get_report_path(previous_id)
    storage.get_report_path(current_id)
    previous = extract_structured_data(previous_id, extract_report_text(previous_id, storage).extracted_text)
    current = extract_structured_data(current_id, extract_report_text(current_id, storage).extracted_text)
    pmap, cmap = {}, {}
    for result in previous.results:
        pmap.setdefault(_key(result.test_name), []).append(result)
    for result in current.results:
        cmap.setdefault(_key(result.test_name), []).append(result)
    common = pmap.keys() & cmap.keys()
    comparisons = []
    for key in sorted(common):
        # Multiple same-name values cannot be paired reliably.
        pitems, citems = pmap[key], cmap[key]
        if len(pitems) != 1 or len(citems) != 1:
            comparisons.append(ComparedTest(test_name=citems[0].test_name,
                previous_value=None, current_value=None, status="ambiguous_value"))
            continue
        p, c = pitems[0], citems[0]
        status, difference = "comparable", None
        if p.needs_review or c.needs_review:
            status = "ambiguous_value"
        elif p.value is None or c.value is None:
            status = "missing_value"
        elif not p.unit or not c.unit:
            status = "missing_unit"
        elif _unit(p.unit) != _unit(c.unit):
            status = "unit_mismatch"
        else:
            pn, cn = _number(p.value), _number(c.value)
            if pn is None or cn is None:
                status = "ambiguous_value"
            else:
                difference = format(cn - pn, "f")
                if "." in difference:
                    difference = difference.rstrip("0").rstrip(".")
                if difference in {"", "-0"}:
                    difference = "0"
        comparisons.append(ComparedTest(test_name=c.test_name, previous_value=p.value,
            previous_unit=p.unit, previous_reference_range=p.reference_range,
            current_value=c.value, current_unit=c.unit, current_reference_range=c.reference_range,
            difference=difference, status=status))
    return ReportComparisonResponse(previous_report_id=previous_id, current_report_id=current_id,
        previous_report_date=previous.report_date, current_report_date=current.report_date,
        comparisons=comparisons,
        missing_from_previous=[cmap[k][0].test_name for k in sorted(cmap.keys() - pmap.keys())],
        missing_from_current=[pmap[k][0].test_name for k in sorted(pmap.keys() - cmap.keys())],
        note=NOTE, disclaimer=DISCLAIMER)
