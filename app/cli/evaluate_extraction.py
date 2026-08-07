from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.evaluation.cache import MinerUParseCache
from app.evaluation.providers import build_real_normalizer, build_real_parser
from app.evaluation.report import render_markdown_report
from app.evaluation.runner import ExtractionEvaluationRunner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("evaluation_data/manifest.json"),
    )
    parser.add_argument("--variant", default="baseline")
    parser.add_argument("--max-documents", type=int)
    args = parser.parse_args()

    settings = get_settings()
    document_parser = build_real_parser(settings)
    normalizer = build_real_normalizer(settings)
    dataset_root = args.manifest.parent
    runner = ExtractionEvaluationRunner(
        parser=document_parser,
        normalizer=normalizer,
        cache=MinerUParseCache(dataset_root / "cache" / "mineru"),
        poll_interval_seconds=settings.mineru_poll_interval_seconds,
        progress=print,
    )
    summary, documents, output_directory = runner.run(
        manifest_path=args.manifest,
        variant_name=args.variant,
        output_root=dataset_root / "results",
        max_documents=args.max_documents,
    )
    (output_directory / "report.md").write_text(
        render_markdown_report(summary, documents),
        encoding="utf-8",
    )
    print(f"Evaluation complete: {output_directory}")
    print(
        f"field_accuracy={summary.field_micro_accuracy:.2%} "
        f"line_item_f1={summary.line_item_f1:.2%} "
        f"evidence_coverage={summary.evidence_coverage:.2%}"
    )


if __name__ == "__main__":
    main()
