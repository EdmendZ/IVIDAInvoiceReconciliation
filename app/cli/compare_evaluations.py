from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from app.evaluation.comparison import (
    rank_variants,
    render_comparison_markdown,
)
from app.evaluation.models import EvaluationSummary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("summaries", nargs="+", type=Path)
    parser.add_argument(
        "--max-cost-aud-per-document",
        type=Decimal,
        default=Decimal("0.10"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation_data/results/comparison.md"),
    )
    args = parser.parse_args()

    summaries = [
        EvaluationSummary.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        for path in args.summaries
    ]
    ranked = rank_variants(
        summaries,
        max_cost_aud_per_document=args.max_cost_aud_per_document,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_comparison_markdown(
            ranked,
            max_cost_aud_per_document=args.max_cost_aud_per_document,
        ),
        encoding="utf-8",
    )
    print(f"Comparison written: {args.output}")
    if ranked:
        print(f"Recommended variant: {ranked[0].name}")


if __name__ == "__main__":
    main()
