from __future__ import annotations

from decimal import Decimal

from app.evaluation.models import EvaluationSummary, RankedVariant


def rank_variants(
    summaries: list[EvaluationSummary],
    *,
    max_cost_aud_per_document: Decimal,
) -> list[RankedVariant]:
    def within_budget(summary: EvaluationSummary) -> bool:
        return (
            summary.average_cost_aud is not None
            and summary.average_cost_aud <= max_cost_aud_per_document
        )

    ordered = sorted(
        summaries,
        key=lambda item: (
            not within_budget(item),
            -item.field_micro_accuracy,
            -item.line_item_f1,
            -item.evidence_coverage,
            (
                item.average_cost_aud
                if item.average_cost_aud is not None
                else Decimal("Infinity")
            ),
            item.variant_name,
        ),
    )
    result: list[RankedVariant] = []
    for index, summary in enumerate(ordered, start=1):
        budget = within_budget(summary)
        rationale = [
            f"field accuracy {summary.field_micro_accuracy:.2%}",
            f"line-item F1 {summary.line_item_f1:.2%}",
            f"evidence coverage {summary.evidence_coverage:.2%}",
        ]
        if summary.average_cost_aud is None:
            rationale.append("cost rate not configured")
        elif budget:
            rationale.append(
                f"AUD {summary.average_cost_aud:.6f} per document, within budget"
            )
        else:
            rationale.append(
                f"AUD {summary.average_cost_aud:.6f} per document, over budget"
            )
        result.append(
            RankedVariant(
                rank=index,
                name=summary.variant_name,
                within_budget=budget,
                field_micro_accuracy=summary.field_micro_accuracy,
                line_item_f1=summary.line_item_f1,
                evidence_coverage=summary.evidence_coverage,
                average_cost_aud=summary.average_cost_aud,
                rationale=rationale,
            )
        )
    return result


def render_comparison_markdown(
    ranked: list[RankedVariant],
    *,
    max_cost_aud_per_document: Decimal,
) -> str:
    lines = [
        "# Normalization Variant Comparison",
        "",
        (
            "Budget guardrail: "
            f"AUD {max_cost_aud_per_document:.6f} per document."
        ),
        "",
        "| Rank | Variant | Field accuracy | Line F1 | Evidence | Cost/doc | Budget |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for item in ranked:
        cost = (
            f"AUD {item.average_cost_aud:.6f}"
            if item.average_cost_aud is not None
            else "not configured"
        )
        lines.append(
            f"| {item.rank} | {item.name} | "
            f"{item.field_micro_accuracy:.2%} | {item.line_item_f1:.2%} | "
            f"{item.evidence_coverage:.2%} | {cost} | "
            f"{'yes' if item.within_budget else 'no'} |"
        )
    lines.extend(
        [
            "",
            "Ranking first enforces the cost guardrail, then compares field "
            "accuracy, line-item F1 and evidence coverage.",
            "",
            "Results apply only to the synthetic evaluation dataset.",
            "",
        ]
    )
    return "\n".join(lines)
