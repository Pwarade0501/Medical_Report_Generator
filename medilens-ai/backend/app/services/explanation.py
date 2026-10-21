"""Build patient-friendly explanations from Phase 5 structured results."""
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.core.errors import AIInputLimitError, InvalidAIOutputError, PdfExtractionError
from app.models.schemas import (
    AIExplanationDraft,
    ReportExplanationResponse,
    ReportResultExplanation,
    StructuredReportResponse,
)
from app.services.ai_provider import generate_explanation
from app.services.structured_extraction import is_supported_analyte

_VALUE_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_RANGE_RE = re.compile(
    r"^\s*(?:reference\s*(?:range)?\s*[:=]?\s*)?"
    r"([+-]?\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*([+-]?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
_UNSAFE_PATTERNS = (
    re.compile(r"\b(?:you have|you may have|you likely have|you are diagnosed with|diagnosed with|means you have|indicates you have)\b", re.I),
    re.compile(r"\b(?:prescribe|prescription|treatment plan)\b", re.I),
    re.compile(r"\b(?:you should|you must|you need to)\s+(?:take|start|stop|change|increase|decrease)\b", re.I),
    re.compile(r"\b(?:should|could|would)\s+i\s+(?:take|start|stop|change|increase|decrease)\b", re.I),
    re.compile(r"\b(?:start|stop|change|increase|decrease)\s+(?:your\s+)?(?:medication|medicine|drug|dose)\b", re.I),
    re.compile(r"\b(?:suggests?|indicates?|confirms?)\s+(?:that\s+)?(?:you\s+)?(?:have\s+)?(?:diabetes|prediabetes|cancer|kidney disease|anemia|hypertension|heart disease|infection)\b", re.I),
)
MAX_EXPLANATION_RESULTS = 100
MAX_PROVIDER_INPUT_CHARS = 30_000
_DISCLAIMER = {
    "en": "Educational information only. This is not a diagnosis or medical advice. Discuss your report with a qualified healthcare professional.",
    "hi": "यह जानकारी केवल शैक्षिक उद्देश्य के लिए है। यह निदान या चिकित्सा सलाह नहीं है। अपनी रिपोर्ट पर योग्य स्वास्थ्य पेशेवर से चर्चा करें।",
    "mr": "ही माहिती केवळ शैक्षणिक उद्देशाने आहे. हे निदान किंवा वैद्यकीय सल्ला नाही. आपल्या अहवालाबद्दल पात्र आरोग्यतज्ज्ञांशी चर्चा करा.",
}
_COMPARISON_NOTE = {
    "en": "The range comparison is a simple software comparison with the range printed in this report. It does not determine clinical normality.",
    "hi": "यह तुलना रिपोर्ट में दी गई सीमा से एक साधारण सॉफ़्टवेयर तुलना है। इससे चिकित्सकीय सामान्यता निर्धारित नहीं होती।",
    "mr": "ही तुलना अहवालातील संदर्भ मर्यादेशी केलेली साधी सॉफ्टवेअर तुलना आहे. यावरून वैद्यकीय सामान्यता ठरत नाही.",
}


def compare_with_reported_range(value: str | None, reference_range: str | None) -> str:
    if not value or not reference_range or not _VALUE_RE.fullmatch(value.strip()):
        return "not_comparable"
    match = _RANGE_RE.fullmatch(reference_range)
    if not match:
        return "not_comparable"
    try:
        measured = Decimal(value)
        lower, upper = Decimal(match.group(1)), Decimal(match.group(2))
    except InvalidOperation:
        return "not_comparable"
    if not all(number.is_finite() for number in (measured, lower, upper)) or lower > upper:
        return "not_comparable"
    return "within_range" if lower <= measured <= upper else "outside_range"


def _ensure_safe_text(draft: AIExplanationDraft) -> None:
    generated = [draft.summary, *draft.questions_for_doctor]
    generated.extend(item.explanation for item in draft.result_explanations)
    if any(pattern.search(text) for text in generated for pattern in _UNSAFE_PATTERNS):
        raise InvalidAIOutputError("The AI provider returned content outside the educational safety limits.")


def explain_structured_report(
    report_id: UUID,
    structured: StructuredReportResponse,
    language: str,
) -> ReportExplanationResponse:
    if not structured.results:
        raise PdfExtractionError("No structured test results are available to explain.")
    if len(structured.results) > MAX_EXPLANATION_RESULTS:
        raise AIInputLimitError(f"A maximum of {MAX_EXPLANATION_RESULTS} results can be explained at once.")

    eligible: list[tuple[int, object]] = []
    for index, result in enumerate(structured.results):
        if not result.needs_review and is_supported_analyte(result.test_name):
            eligible.append((index, result))
    if not eligible:
        raise PdfExtractionError("No clear, supported test results are available to explain.")

    # Only send parsed fields needed for explanation; source lines and report identifiers stay local.
    provider_data = [
        {
            "result_index": index,
            "test_name": result.test_name,
            "value": result.value,
            "unit": result.unit,
            "reference_range": result.reference_range,
            "printed_flag": result.flag,
        }
        for index, result in eligible
    ]
    if len(str(provider_data)) > MAX_PROVIDER_INPUT_CHARS:
        raise AIInputLimitError("The structured results exceed the AI explanation input limit.")
    draft = generate_explanation(provider_data, language)
    _ensure_safe_text(draft)

    expected_indexes = {index for index, _ in eligible}
    actual_indexes = [item.result_index for item in draft.result_explanations]
    if len(actual_indexes) != len(set(actual_indexes)) or set(actual_indexes) != expected_indexes:
        raise InvalidAIOutputError("The AI provider did not explain the supplied results consistently.")
    explanation_by_index = {item.result_index: item.explanation for item in draft.result_explanations}

    results: list[ReportResultExplanation] = []
    warnings = [f"Line {item.line_number}: {item.message}" for item in structured.warnings]
    for index, item in enumerate(structured.results):
        supported = is_supported_analyte(item.test_name)
        if item.needs_review:
            explanation_text = "This result could not be read clearly and needs review against the original report."
        elif not supported:
            explanation_text = "This test is outside the tests supported by this educational explanation feature."
            warnings.append(f"{item.test_name}: this test is not currently supported for explanation.")
        else:
            explanation_text = explanation_by_index[index]
        if item.needs_review:
            warnings.append(f"{item.test_name}: the extracted result needs review.")
        results.append(ReportResultExplanation(
            test_name=item.test_name,
            reported_value=item.value,
            unit=item.unit,
            reference_range=item.reference_range,
            printed_flag=item.flag,
            range_comparison=compare_with_reported_range(item.value, item.reference_range),
            explanation=explanation_text,
            needs_review=item.needs_review,
        ))

    return ReportExplanationResponse(
        report_id=report_id,
        report_date=structured.report_date,
        language=language,
        summary=draft.summary,
        result_explanations=results,
        questions_for_doctor=draft.questions_for_doctor,
        warnings=warnings,
        comparison_note=_COMPARISON_NOTE[language],
        disclaimer=_DISCLAIMER[language],
    )
