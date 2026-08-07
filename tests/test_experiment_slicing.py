from app.evaluation.models import ComparisonCounts, DocumentEvaluation
from app.experiments.slicing import build_error_slices


def _document(
    *,
    schema_valid: bool,
    errors: list[str],
    evidence_covered: int,
) -> DocumentEvaluation:
    return DocumentEvaluation(
        case_id="case-08-po-mismatch",
        business_scenario="purchase_order_conflict",
        document_path="invoice.pdf",
        document_type="invoice",
        schema_valid=schema_valid,
        counts=ComparisonCounts(
            correct=1,
            total=2,
            matched_lines=0,
            missing_lines=0,
            extra_lines=0,
            evidence_covered=evidence_covered,
            evidence_total=2,
            errors=errors,
        ),
        latency_ms=10,
        parser_cache_hit=True,
        parser_model="vlm",
        normalizer_model="model",
        prompt_version="prompt",
    )


def test_slices_keep_failures_scenarios_and_field_groups() -> None:
    slices = build_error_slices(
        [
            _document(
                schema_valid=False,
                errors=[],
                evidence_covered=2,
            ),
            _document(
                schema_valid=True,
                errors=[
                    "purchase_order_number: expected='PO-1' actual='PO-2'"
                ],
                evidence_covered=1,
            ),
        ]
    )
    indexed = {(item.dimension, item.value): item for item in slices}

    assert indexed[("error_type", "schema_failure")].document_count == 1
    assert indexed[("field_group", "purchase")].error_count == 1
    assert indexed[("document_type", "invoice")].document_count == 2
    scenario = indexed[("business_scenario", "purchase_order_conflict")]
    assert scenario.document_count == 2
    assert scenario.error_count == 2
    assert indexed[("error_type", "evidence_missing")].error_count == 1


def test_slices_are_stably_sorted() -> None:
    slices = build_error_slices(
        [_document(schema_valid=True, errors=[], evidence_covered=2)]
    )

    assert [(item.dimension, item.value) for item in slices] == sorted(
        (item.dimension, item.value) for item in slices
    )
