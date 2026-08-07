"""Pure, deterministic error slicing for extraction evaluation results."""

from collections import defaultdict

from app.evaluation.models import DocumentEvaluation
from app.experiments.domain import ErrorSlice


FIELD_GROUPS = {
    "document_type": "identity",
    "document_number": "identity",
    "document_date": "identity",
    "supplier": "identity",
    "location": "identity",
    "purchase_order_number": "purchase",
    "currency": "amount",
    "subtotal": "amount",
    "tax_total": "amount",
    "total": "amount",
    "items": "line_item",
}


def _error_bucket(message: str) -> tuple[str, str]:
    if message.startswith("missing line "):
        return "error_type", "missing_line"
    if message.startswith("extra line "):
        return "error_type", "extra_line"
    field_path = message.split(":", 1)[0]
    root = field_path.split(".", 1)[0]
    return "field_group", FIELD_GROUPS.get(root, "other")


def build_error_slices(
    documents: list[DocumentEvaluation],
) -> list[ErrorSlice]:
    document_ids: dict[tuple[str, str], set[int]] = defaultdict(set)
    error_counts: dict[tuple[str, str], int] = defaultdict(int)

    def record(key: tuple[str, str], index: int, errors: int = 0) -> None:
        document_ids[key].add(index)
        error_counts[key] += errors

    for index, document in enumerate(documents):
        document_errors = len(document.counts.errors) + (not document.schema_valid)
        record(("document_type", document.document_type), index, document_errors)
        record(("business_scenario", document.business_scenario), index, document_errors)

        if not document.schema_valid:
            record(("error_type", "schema_failure"), index, 1)
        for message in document.counts.errors:
            record(_error_bucket(message), index, 1)

        missing_evidence = (
            document.counts.evidence_total - document.counts.evidence_covered
        )
        if missing_evidence > 0:
            record(("error_type", "evidence_missing"), index, missing_evidence)

    return [
        ErrorSlice(
            dimension=dimension,
            value=value,
            document_count=len(document_ids[(dimension, value)]),
            error_count=error_counts[(dimension, value)],
        )
        for dimension, value in sorted(document_ids)
    ]
