from app.evaluation.models import DocumentEvaluation, EvaluationSummary


def render_markdown_report(
    summary: EvaluationSummary,
    documents: list[DocumentEvaluation],
) -> str:
    worst = sorted(
        documents,
        key=lambda item: item.counts.field_accuracy,
    )[:5]
    lines = [
        f"# Extraction Evaluation: {summary.variant_name}",
        "",
        "Synthetic Australian pizza procurement dataset.",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Documents | {summary.document_count} |",
        f"| Schema valid | {summary.schema_valid_rate:.2%} |",
        f"| Field micro accuracy | {summary.field_micro_accuracy:.2%} |",
        f"| Line-item F1 | {summary.line_item_f1:.2%} |",
        f"| Evidence coverage | {summary.evidence_coverage:.2%} |",
        f"| P50 normalization latency | {summary.p50_latency_ms} ms |",
        f"| P95 normalization latency | {summary.p95_latency_ms} ms |",
        f"| MinerU cache hits | {summary.parser_cache_hits} |",
        (
            "| Failed documents | "
            f"{sum(not item.schema_valid for item in documents)} |"
        ),
        (
            "| Average normalization cost | "
            f"AUD {summary.average_cost_aud:.6f} |"
            if summary.average_cost_aud is not None
            else "| Average normalization cost | not configured |"
        ),
        "",
        "## Lowest-scoring documents",
        "",
    ]
    for item in worst:
        failure = (
            f"; failed at {item.error_stage}: {item.error_code}"
            if not item.schema_valid
            else ""
        )
        lines.append(
            f"- `{item.case_id}` / `{item.document_type}`: "
            f"{item.counts.field_accuracy:.2%}; "
            f"{len(item.counts.errors)} recorded differences{failure}"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "These results measure a synthetic evaluation set. They do not "
            "establish customer ROI, regulatory compliance, or production SLA.",
            "",
        ]
    )
    return "\n".join(lines)
