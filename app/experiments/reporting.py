"""Safe deterministic text reports for experiment promotion decisions."""

from app.experiments.domain import PromotionDecision


def render_promotion_markdown(decision: PromotionDecision) -> str:
    lines = [
        "# Extraction Promotion Decision",
        "",
        f"- Outcome: **{decision.outcome.value}**",
        f"- Baseline run: `{decision.baseline_run_id}`",
        f"- Candidate run: `{decision.candidate_run_id}`",
        "",
        "## Checks",
        "",
        "| Check | Gate | Passed | Baseline | Candidate | Threshold |",
        "|---|---|---:|---|---|---|",
    ]
    for check in decision.checks:
        lines.append(
            f"| {check.code} | {'hard' if check.hard_gate else 'quality'} | "
            f"{'yes' if check.passed else 'no'} | {check.baseline_value} | "
            f"{check.candidate_value} | {check.threshold} |"
        )
    if decision.reasons:
        lines.extend(["", "## Reasons", ""])
        lines.extend(f"- {reason}" for reason in decision.reasons)
    return "\n".join(lines) + "\n"
