import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.models import (
    ComparisonCounts,
    DocumentEvaluation,
    EvaluationSummary,
)
from app.experiments.domain import (
    DatasetIdentity,
    EvaluationRunStatus,
    ExperimentDefinition,
    ExperimentRole,
    ExperimentThresholds,
)
from app.experiments.runner import (
    ExperimentExecutionFailed,
    ExperimentRunner,
    load_dataset_identity,
)
from app.infra.postgres_experiment_repository import ExperimentNotFound


NOW = datetime(2026, 8, 7, tzinfo=UTC)


class Repository:
    def __init__(self, definition: ExperimentDefinition | None) -> None:
        self.definition = definition
        self.runs = {}

    def get_definition(self, definition_id):
        if self.definition and self.definition.experiment_id == definition_id:
            return self.definition
        return None

    def create_run(self, run):
        self.runs[run.run_id] = run
        return run

    def mark_run_running(self, run_id, *, started_at):
        return self._update(
            run_id, status=EvaluationRunStatus.RUNNING, started_at=started_at
        )

    def complete_run(self, run_id, *, summary, documents, slices, completed_at):
        return self._update(
            run_id,
            status=EvaluationRunStatus.COMPLETED,
            summary=summary,
            documents=documents,
            slices=slices,
            completed_at=completed_at,
        )

    def fail_run(self, run_id, *, error_code, error_message, completed_at):
        return self._update(
            run_id,
            status=EvaluationRunStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            completed_at=completed_at,
        )

    def cancel_run(self, run_id, *, cancelled_at):
        return self._update(
            run_id,
            status=EvaluationRunStatus.CANCELLED,
            cancelled_at=cancelled_at,
        )

    def _update(self, run_id, **changes):
        self.runs[run_id] = self.runs[run_id].model_copy(update=changes)
        return self.runs[run_id]


class Evaluator:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def _manifest(root: Path) -> Path:
    source = root / "invoice.pdf"
    root.mkdir(parents=True)
    source.write_bytes(b"invoice")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "cases": [
                    {
                        "case_id": "case-1",
                        "expected_outcome": "exact",
                        "documents": ["invoice.pdf"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _definition(manifest: Path) -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_id="definition-1",
        name="baseline",
        role=ExperimentRole.BASELINE,
        manifest_path=str(manifest),
        dataset_identity=load_dataset_identity(manifest),
        parser_provider="mineru",
        parser_model="vlm",
        parser_version="1",
        normalizer_provider="fixture",
        normalizer_model="model",
        prompt_version="prompt",
        schema_version="1",
        parameters={},
        thresholds=ExperimentThresholds(),
        created_by="admin-1",
        created_at=NOW,
    )


def _result(tmp_path: Path):
    documents = [
        DocumentEvaluation(
            case_id="case-1",
            business_scenario="exact",
            document_path="invoice.pdf",
            document_type="invoice",
            schema_valid=False,
            counts=ComparisonCounts(
                correct=0,
                total=1,
                matched_lines=0,
                missing_lines=0,
                extra_lines=0,
                evidence_covered=0,
                evidence_total=1,
            ),
            latency_ms=1,
            parser_cache_hit=True,
            parser_model="vlm",
            normalizer_model="model",
            prompt_version="prompt",
            error_stage="normalizer",
        )
    ]
    summary = EvaluationSummary(
        variant_name="baseline",
        document_count=1,
        schema_valid_rate=0,
        field_micro_accuracy=0,
        line_item_f1=1,
        evidence_coverage=0,
        p50_latency_ms=1,
        p95_latency_ms=1,
        parser_cache_hits=1,
    )
    return summary, documents, tmp_path / "output"


def test_partial_failure_is_persisted(tmp_path: Path) -> None:
    definition = _definition(_manifest(tmp_path / "dataset"))
    repository = Repository(definition)
    runner = ExperimentRunner(
        repository=repository,
        evaluator=Evaluator(_result(tmp_path)),
        now=lambda: NOW,
        new_id=lambda: "run-1",
    )

    completed = runner.run(definition.experiment_id, tmp_path / "results")

    assert completed.summary.document_count == 1
    assert any(item.value == "schema_failure" for item in completed.slices)


@pytest.mark.parametrize("error", [RuntimeError("provider down")])
def test_evaluator_exception_is_persisted(tmp_path: Path, error: Exception) -> None:
    definition = _definition(_manifest(tmp_path / "dataset"))
    repository = Repository(definition)
    runner = ExperimentRunner(
        repository=repository,
        evaluator=Evaluator(error=error),
        now=lambda: NOW,
        new_id=lambda: "run-failed",
    )

    with pytest.raises(ExperimentExecutionFailed):
        runner.run(definition.experiment_id, tmp_path / "results")

    assert repository.runs["run-failed"].status == EvaluationRunStatus.FAILED
    assert repository.runs["run-failed"].error_message == "experiment evaluation failed"


def test_keyboard_interrupt_is_persisted_as_cancelled(tmp_path: Path) -> None:
    definition = _definition(_manifest(tmp_path / "dataset"))
    repository = Repository(definition)
    runner = ExperimentRunner(
        repository=repository,
        evaluator=Evaluator(error=KeyboardInterrupt()),
        now=lambda: NOW,
        new_id=lambda: "run-cancelled",
    )

    with pytest.raises(KeyboardInterrupt):
        runner.run(definition.experiment_id, tmp_path / "results")

    assert repository.runs["run-cancelled"].status == EvaluationRunStatus.CANCELLED


def test_missing_definition_does_not_create_run(tmp_path: Path) -> None:
    repository = Repository(None)
    with pytest.raises(ExperimentNotFound):
        ExperimentRunner(repository=repository, evaluator=Evaluator()).run(
            "missing", tmp_path
        )
    assert repository.runs == {}


def test_dataset_mismatch_fails_before_evaluator_call(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "dataset")
    definition = _definition(manifest).model_copy(
        update={
            "dataset_identity": DatasetIdentity(
                version="1.0.0",
                manifest_sha256="a" * 64,
                document_sha256s=("b" * 64,),
            )
        }
    )
    repository = Repository(definition)
    evaluator = Evaluator()
    runner = ExperimentRunner(
        repository=repository,
        evaluator=evaluator,
        now=lambda: NOW,
        new_id=lambda: "run-mismatch",
    )

    with pytest.raises(ExperimentExecutionFailed) as raised:
        runner.run(definition.experiment_id, tmp_path / "results")

    assert raised.value.code == "DATASET_IDENTITY_MISMATCH"
    assert evaluator.calls == 0


def test_each_execution_gets_a_distinct_run_id(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "dataset")
    definition = _definition(manifest)
    repository = Repository(definition)
    identifiers = iter(("run-1", "run-2"))
    runner = ExperimentRunner(
        repository=repository,
        evaluator=Evaluator(_result(tmp_path)),
        now=lambda: NOW + timedelta(seconds=len(repository.runs)),
        new_id=lambda: next(identifiers),
    )

    first = runner.run(definition.experiment_id, tmp_path / "results")
    second = runner.run(definition.experiment_id, tmp_path / "results")

    assert first.run_id != second.run_id


def test_create_cli_persists_exact_runtime_provenance(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.cli import create_experiment

    manifest = _manifest(tmp_path / "dataset")
    captured = []
    settings = SimpleNamespace(
        mineru_language="en",
        normalization_enable_thinking=False,
        normalization_max_output_tokens=4096,
        normalization_max_retries=0,
        normalization_timeout_seconds=120,
    )
    parser = SimpleNamespace(provider_name="mineru", model_name="vlm")
    normalizer = SimpleNamespace(
        provider_name="openai-compatible",
        model_name="qwen-plus",
        prompt_version="sha256:prompt",
    )

    class CapturingRepository:
        def __init__(self, factory) -> None:
            del factory

        def create_definition(self, definition):
            captured.append(definition)
            return definition

    monkeypatch.setattr(create_experiment, "get_settings", lambda: settings)
    monkeypatch.setattr(create_experiment, "build_real_parser", lambda _: parser)
    monkeypatch.setattr(
        create_experiment, "build_real_normalizer", lambda _: normalizer
    )
    monkeypatch.setattr(create_experiment, "parser_runtime_version", lambda: "2.1.0")
    monkeypatch.setattr(
        create_experiment, "document_schema_version", lambda: "schema-1"
    )
    monkeypatch.setattr(create_experiment, "_active_admin_id", lambda _: "admin-1")
    monkeypatch.setattr(create_experiment, "get_session_factory", lambda: object())
    monkeypatch.setattr(
        create_experiment, "PostgresExperimentRepository", CapturingRepository
    )

    exit_code = create_experiment.main(
        [
            "--name",
            "qwen-baseline",
            "--role",
            "baseline",
            "--manifest",
            str(manifest),
            "--required-schema-valid-rate",
            "1",
            "--minimum-field-accuracy",
            "0.95",
            "--minimum-line-item-f1",
            "0.95",
            "--minimum-evidence-coverage",
            "0.90",
            "--max-cost-aud-per-document",
            "0.10",
        ]
    )

    assert exit_code == 0
    assert len(captured) == 1
    assert captured[0].normalizer_model == "qwen-plus"
    assert captured[0].parser_version == "2.1.0"
    assert captured[0].thresholds.max_cost_aud_per_document == Decimal("0.10")
    assert capsys.readouterr().out.strip() == captured[0].experiment_id
