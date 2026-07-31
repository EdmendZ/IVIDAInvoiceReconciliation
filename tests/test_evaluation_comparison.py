from decimal import Decimal

from app.evaluation.comparison import rank_variants
from app.evaluation.models import EvaluationSummary


def _summary(
    name: str,
    accuracy: str,
    cost: str | None,
) -> EvaluationSummary:
    return EvaluationSummary(
        variant_name=name,
        document_count=17,
        schema_valid_rate=Decimal("1"),
        field_micro_accuracy=Decimal(accuracy),
        line_item_f1=Decimal(accuracy),
        evidence_coverage=Decimal("0.9"),
        p50_latency_ms=100,
        p95_latency_ms=200,
        average_cost_aud=Decimal(cost) if cost is not None else None,
        total_cost_aud=(
            Decimal(cost) * Decimal(17) if cost is not None else None
        ),
        parser_cache_hits=17,
    )


def test_ranker_enforces_budget_then_accuracy() -> None:
    ranked = rank_variants(
        [
            _summary("over-budget", "0.99", "0.20"),
            _summary("accurate-cheap", "0.95", "0.05"),
            _summary("inaccurate-cheap", "0.80", "0.01"),
        ],
        max_cost_aud_per_document=Decimal("0.10"),
    )

    assert [item.name for item in ranked] == [
        "accurate-cheap",
        "inaccurate-cheap",
        "over-budget",
    ]
