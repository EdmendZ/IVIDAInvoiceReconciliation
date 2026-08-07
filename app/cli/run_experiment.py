"""Execute a stored extraction experiment against the real providers."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.evaluation.cache import MinerUParseCache
from app.evaluation.providers import (
    build_real_normalizer,
    build_real_parser,
    document_schema_version,
    evaluation_parameters,
    parser_runtime_version,
)
from app.evaluation.report import render_markdown_report
from app.evaluation.runner import ExtractionEvaluationRunner
from app.experiments.runner import ExperimentRunner
from app.infra.database import get_session_factory
from app.infra.postgres_experiment_repository import (
    ExperimentNotFound,
    PostgresExperimentRepository,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an extraction experiment")
    parser.add_argument("--definition-id", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--max-documents", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    settings = get_settings()
    repository = PostgresExperimentRepository(get_session_factory())
    definition = repository.get_definition(args.definition_id)
    if definition is None:
        raise ExperimentNotFound(args.definition_id)

    document_parser = build_real_parser(settings)
    normalizer = build_real_normalizer(settings)
    actual = (
        document_parser.provider_name,
        document_parser.model_name,
        normalizer.provider_name,
        normalizer.model_name,
        normalizer.prompt_version,
        parser_runtime_version(),
        document_schema_version(),
        evaluation_parameters(settings),
    )
    expected = (
        definition.parser_provider,
        definition.parser_model,
        definition.normalizer_provider,
        definition.normalizer_model,
        definition.prompt_version,
        definition.parser_version,
        definition.schema_version,
        definition.parameters,
    )
    if actual != expected:
        raise RuntimeError(
            "runtime provider provenance differs from experiment definition"
        )

    evaluator = ExtractionEvaluationRunner(
        parser=document_parser,
        normalizer=normalizer,
        cache=MinerUParseCache(
            Path(definition.manifest_path).parent / "cache" / "mineru"
        ),
        poll_interval_seconds=settings.mineru_poll_interval_seconds,
    )
    completed = ExperimentRunner(repository=repository, evaluator=evaluator).run(
        definition.experiment_id,
        output_root=args.output_root,
        max_documents=args.max_documents,
    )
    report_path = args.output_root / f"{completed.run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_markdown_report(completed.summary, completed.documents),
        encoding="utf-8",
    )
    summary = completed.summary
    print(f"run_id={completed.run_id}")
    print(
        f"schema_valid_rate={summary.schema_valid_rate:.2%} "
        f"field_accuracy={summary.field_micro_accuracy:.2%} "
        f"line_item_f1={summary.line_item_f1:.2%} "
        f"evidence_coverage={summary.evidence_coverage:.2%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
