"""Persisted orchestration for reproducible extraction evaluations."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.evaluation.models import DocumentEvaluation, EvaluationSummary
from app.experiments.domain import DatasetIdentity, EvaluationRun, EvaluationRunStatus
from app.experiments.ports import ExperimentRepository
from app.experiments.slicing import build_error_slices
from app.infra.postgres_experiment_repository import ExperimentNotFound


class Evaluator(Protocol):
    def run(
        self,
        *,
        manifest_path: Path,
        variant_name: str,
        output_root: Path,
        max_documents: int | None = None,
    ) -> tuple[EvaluationSummary, list[DocumentEvaluation], Path]: ...


class DatasetIdentityMismatch(RuntimeError):
    pass


class ExperimentExecutionFailed(RuntimeError):
    def __init__(self, run_id: str, code: str) -> None:
        self.run_id = run_id
        self.code = code
        super().__init__(f"experiment run {run_id} failed ({code})")


def load_dataset_identity(manifest_path: Path) -> DatasetIdentity:
    """Hash the exact manifest bytes and every referenced source document."""

    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    document_paths: list[Path] = []
    for case in manifest["cases"]:
        if not case.get("expected_outcome"):
            raise ValueError(
                f"manifest case {case.get('case_id', '<unknown>')} lacks expected_outcome"
            )
        document_paths.extend(
            manifest_path.parent / relative_path for relative_path in case["documents"]
        )
    document_paths.sort(key=lambda path: path.as_posix())
    return DatasetIdentity(
        version=str(manifest["version"]),
        manifest_sha256=sha256(manifest_bytes).hexdigest(),
        document_sha256s=tuple(
            sha256(path.read_bytes()).hexdigest() for path in document_paths
        ),
    )


class ExperimentRunner:
    def __init__(
        self,
        *,
        repository: ExperimentRepository,
        evaluator: Evaluator,
        now: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._evaluator = evaluator
        self._now = now or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: str(uuid4()))

    def run(
        self,
        definition_id: str,
        output_root: Path,
        max_documents: int | None = None,
    ) -> EvaluationRun:
        definition = self._repository.get_definition(definition_id)
        if definition is None:
            raise ExperimentNotFound(definition_id)

        run = EvaluationRun(
            run_id=self._new_id(),
            experiment_id=definition.experiment_id,
            status=EvaluationRunStatus.QUEUED,
            created_at=self._now(),
        )
        self._repository.create_run(run)
        self._repository.mark_run_running(run.run_id, started_at=self._now())

        try:
            manifest_path = Path(definition.manifest_path)
            actual_identity = load_dataset_identity(manifest_path)
            if actual_identity != definition.dataset_identity:
                raise DatasetIdentityMismatch(
                    "manifest or source document hashes differ from the definition"
                )
            summary, documents, _ = self._evaluator.run(
                manifest_path=manifest_path,
                variant_name=definition.name,
                output_root=output_root,
                max_documents=max_documents,
            )
            return self._repository.complete_run(
                run.run_id,
                summary=summary,
                documents=documents,
                slices=build_error_slices(documents),
                completed_at=self._now(),
            )
        except KeyboardInterrupt:
            self._repository.cancel_run(run.run_id, cancelled_at=self._now())
            raise
        except Exception as exc:
            code = (
                "DATASET_IDENTITY_MISMATCH"
                if isinstance(exc, DatasetIdentityMismatch)
                else "EVALUATION_FAILED"
            )
            self._repository.fail_run(
                run.run_id,
                error_code=code,
                error_message="experiment evaluation failed",
                completed_at=self._now(),
            )
            raise ExperimentExecutionFailed(run.run_id, code) from exc
