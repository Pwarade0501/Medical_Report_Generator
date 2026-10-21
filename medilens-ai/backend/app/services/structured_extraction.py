"""Conservative rule-based extraction of common lab results from report text.

Only allow-listed analyte names are considered. This deliberately favors a review
warning or a missing field over guessing at OCR-corrupted medical values.
"""
import re
from difflib import SequenceMatcher
from datetime import date, datetime

from app.core.errors import PdfExtractionError
from app.models.schemas import (
    StructuredExtractionWarning,
    StructuredLabResult,
    StructuredReportResponse,
)

_ANALYTES = (
    "Hemoglobin|HbA1c|Glycated Hemoglobin|White Blood Cell Count|WBC|Leukocytes|"
    "Red Blood Cell Count|RBC|Platelet Count|Platelets|Hematocrit|HCT|"
    "Fasting Blood Sugar|FBS|Blood Glucose|Glucose|Creatinine|Blood Urea Nitrogen|BUN|Urea|"
    "Sodium|Potassium|Chloride|Calcium|Total Cholesterol|HDL Cholesterol|LDL Cholesterol|"
    "HDL|LDL|Triglycerides|Alanine Aminotransferase|ALT|SGPT|Aspartate Aminotransferase|AST|SGOT|"
    "Total Bilirubin|Bilirubin|Thyroid Stimulating Hormone|TSH|Vitamin D|25-OH Vitamin D|"
    "Vitamin B12|Ferritin|C-Reactive Protein|CRP|Erythrocyte Sedimentation Rate|ESR|"
    "Mean Corpuscular Volume|MCV|Mean Corpuscular Hemoglobin Concentration|MCHC|"
    "Mean Corpuscular Hemoglobin|MCH"
)
_ANALYTE_RE = re.compile(rf"^\s*(?:[-•*]\s*)?(?P<name>{_ANALYTES})(?=\b|\s|:)", re.IGNORECASE)
_ANALYTE_FIRST_WORDS = tuple(sorted({name.split()[0] for name in _ANALYTES.split("|")}, key=len, reverse=True))
SUPPORTED_ANALYTE_NAMES = frozenset(name.casefold() for name in _ANALYTES.split("|"))
_NUMBER_PATTERN = r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)"
_NUMBER_RE = re.compile(_NUMBER_PATTERN)
_VALUE_RE = re.compile(rf"^\s*(?:(?:result|value)\s*[:=]\s*)?(?P<value>(?:[<>]=?\s*)?{_NUMBER_PATTERN})", re.IGNORECASE)
_TEXT_VALUE_RE = re.compile(
    r"^\s*(?:(?:result|value)\s*[:=]\s*)?(?P<value>Not\s+Detected|Non[- ]?Reactive|"
    r"Not\s+Detected|Negative|Positive|Reactive|Detected|Trace|Present|Absent)", re.IGNORECASE
)
_UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?P<unit>mg/dL|g/dL|mmol/L|µmol/L|umol/L|mEq/L|mIU/L|uIU/mL|"
    r"mIU/mL|ng/mL|pg/mL|mg/L|g/L|U/L|IU/L|mm/hr|mm/h|cells/µL|cells/uL|"
    r"10\^\d+(?:/µL|/uL)?|fL|pg|%)(?![A-Za-z])", re.IGNORECASE
)
_RANGE_RE = re.compile(
    rf"(?P<range>(?:reference\s*(?:range)?\s*[:=]?\s*)?"
    rf"(?:[<>]=?\s*)?{_NUMBER_PATTERN}\s*(?:-|–|—|\bto\b)\s*"
    rf"(?:[<>]=?\s*)?{_NUMBER_PATTERN}(?:\s*%?)?)", re.IGNORECASE
)
_FLAG_RE = re.compile(r"(?<![/\w])(?P<flag>HIGH|LOW|NORMAL|H|L|N)(?!\w)\s*$", re.IGNORECASE)
_DATE_LABEL_RE = re.compile(r"\b(?:report|test|collection|specimen)\s+date\s*[:=-]?\s*(.+)$", re.IGNORECASE)
_DATE_RE = re.compile(
    r"(?P<date>\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|"
    r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|"
    r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b|"
    r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b)"
)


def _parse_date(value: str) -> tuple[date | None, bool]:
    value = value.strip().replace(",", "")
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date(), False
        except ValueError:
            pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(value, fmt).date()
            parts = re.split(r"[-/]", value)
            ambiguous = int(parts[0]) <= 12 and int(parts[1]) <= 12
            return (None if ambiguous else parsed), ambiguous
        except (ValueError, IndexError):
            pass
    return None, True


def _flag_from_text(text: str) -> tuple[str | None, str]:
    match = _FLAG_RE.search(text)
    if not match:
        return None, text
    raw = match.group("flag")
    flag = {"H": "high", "HIGH": "high", "L": "low", "LOW": "low",
            "N": "normal", "NORMAL": "normal"}[raw.upper()]
    return flag, text[:match.start()].rstrip(" \t|,;:-")


def _looks_like_ocr_damaged_lab(line: str) -> bool:
    token_match = re.match(r"\s*([A-Za-z0-9-]+)", line)
    if not token_match or not (_NUMBER_RE.search(line) or _UNIT_RE.search(line)):
        return False
    token = token_match.group(1).lower()
    return any(SequenceMatcher(None, token, name.lower()).ratio() >= 0.78
               for name in _ANALYTE_FIRST_WORDS)


def _extract_measurement(rest: str) -> tuple[str | None, str | None, str | None, str | None]:
    flag, rest = _flag_from_text(rest.strip())
    rest = re.sub(r"^[\s:=|,;()]+", "", rest)
    value_match = _VALUE_RE.match(rest) or _TEXT_VALUE_RE.match(rest)
    if not value_match:
        return None, None, None, flag
    value = value_match.group("value").strip()
    remainder = rest[value_match.end():]
    unit_match = _UNIT_RE.search(remainder)
    unit = unit_match.group("unit") if unit_match else None
    range_match = _RANGE_RE.search(remainder)
    reference_range = range_match.group("range").strip() if range_match else None
    return value, unit, reference_range, flag


def extract_structured_data(report_id, extracted_text: str) -> StructuredReportResponse:
    if not extracted_text or not extracted_text.strip():
        raise PdfExtractionError("No extracted report text is available to structure.")

    lines = extracted_text.splitlines()
    warnings: list[StructuredExtractionWarning] = []
    report_date: date | None = None
    for line_number, line in enumerate(lines, start=1):
        date_label = _DATE_LABEL_RE.search(line)
        if date_label and report_date is None:
            date_match = _DATE_RE.search(date_label.group(1))
            if date_match:
                parsed, ambiguous = _parse_date(date_match.group("date"))
                report_date = parsed
                if ambiguous:
                    warnings.append(StructuredExtractionWarning(
                        line_number=line_number,
                        code="ambiguous_date",
                        message="The report date format is ambiguous; no date was assigned.",
                        source_text=line.strip(),
                    ))

    results: list[StructuredLabResult] = []
    for line_number, line in enumerate(lines, start=1):
        source = line.strip()
        if not source:
            continue
        match = _ANALYTE_RE.match(source)
        if not match:
            if _looks_like_ocr_damaged_lab(source):
                warnings.append(StructuredExtractionWarning(
                    line_number=line_number,
                    code="unrecognized_lab_name",
                    message="This line resembles a laboratory result, but its test name is unclear and was not guessed.",
                    source_text=source,
                ))
            continue
        name = match.group("name").strip()
        value, unit, reference_range, flag = _extract_measurement(source[match.end():])
        needs_review = value is None
        results.append(StructuredLabResult(
            test_name=name,
            value=value,
            unit=unit,
            reference_range=reference_range,
            date=report_date,
            flag=flag,
            source_text=source,
            needs_review=needs_review,
        ))
        if needs_review:
            warnings.append(StructuredExtractionWarning(
                line_number=line_number,
                code="ambiguous_result",
                message="A supported test name was found, but its result could not be read reliably.",
                source_text=source,
            ))

    return StructuredReportResponse(
        report_id=report_id,
        report_date=report_date,
        result_count=len(results),
        results=results,
        warnings=warnings,
    )


def is_supported_analyte(test_name: str) -> bool:
    """Return whether Phase 5 has a known name for this test."""
    return " ".join(test_name.split()).casefold() in SUPPORTED_ANALYTE_NAMES
