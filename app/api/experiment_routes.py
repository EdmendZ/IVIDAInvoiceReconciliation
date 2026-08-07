"""Admin-only APIs for experiment evidence and governed feedback."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.auth_dependencies import require_admin
from app.api.dependencies import get_experiment_repository, get_feedback_service
from app.domain.admin_users import AuthenticatedUser
from app.experiments.domain import (
    DatasetIdentity,
    ExperimentDefinition,
    ExperimentRole,
    ExperimentThresholds,
    FeedbackClassification,
)
from app.experiments.feedback import FeedbackService
from app.experiments.promotion import decide_promotion
from app.infra.postgres_experiment_repository import (
    ExperimentConflict,
    ExperimentNotFound,
    PostgresExperimentRepository,
)

router = APIRouter(tags=["extraction experiments"])


class ExperimentCreateRequest(BaseModel):
    name: str
    role: ExperimentRole
    manifest_path: str
    dataset_identity: DatasetIdentity
    parser_provider: str
    parser_model: str
    parser_version: str
    normalizer_provider: str
    normalizer_model: str
    prompt_version: str
    schema_version: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    thresholds: ExperimentThresholds


class PromotionRequest(BaseModel):
    baseline_run_id: str
    candidate_run_id: str


class FeedbackConfirmationRequest(BaseModel):
    classification: FeedbackClassification
    include_in_gold: bool = False


def _json(model) -> dict:
    return model.model_dump(mode="json")


@router.post("/api/experiments", status_code=status.HTTP_201_CREATED)
def create_experiment(
    request: ExperimentCreateRequest,
    repository: PostgresExperimentRepository = Depends(get_experiment_repository),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    definition = ExperimentDefinition(
        experiment_id=str(uuid4()),
        created_by=user.user_id,
        created_at=datetime.now(UTC),
        **request.model_dump(mode="python"),
    )
    try:
        return _json(repository.create_definition(definition))
    except ExperimentConflict as exc:
        raise HTTPException(
            status_code=409, detail="Experiment already exists"
        ) from exc


@router.get("/api/experiments")
def list_experiments(
    repository: PostgresExperimentRepository = Depends(get_experiment_repository),
    user: AuthenticatedUser = Depends(require_admin),
) -> list[dict]:
    del user
    return [_json(item) for item in repository.list_definitions()]


@router.get("/api/experiments/{experiment_id}")
def get_experiment(
    experiment_id: str,
    repository: PostgresExperimentRepository = Depends(get_experiment_repository),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    del user
    definition = repository.get_definition(experiment_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return _json(definition)


@router.get("/api/experiment-runs")
def list_experiment_runs(
    experiment_id: str | None = None,
    repository: PostgresExperimentRepository = Depends(get_experiment_repository),
    user: AuthenticatedUser = Depends(require_admin),
) -> list[dict]:
    del user
    return [_json(item) for item in repository.list_runs(experiment_id)]


@router.get("/api/experiment-runs/{run_id}")
def get_experiment_run(
    run_id: str,
    repository: PostgresExperimentRepository = Depends(get_experiment_repository),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    del user
    run = repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Experiment run not found")
    return _json(run)


@router.post("/api/promotion-decisions", status_code=status.HTTP_201_CREATED)
def create_promotion_decision(
    request: PromotionRequest,
    repository: PostgresExperimentRepository = Depends(get_experiment_repository),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    baseline = repository.get_run(request.baseline_run_id)
    candidate = repository.get_run(request.candidate_run_id)
    if baseline is None or candidate is None:
        raise HTTPException(status_code=404, detail="Experiment run not found")
    baseline_definition = repository.get_definition(baseline.experiment_id)
    candidate_definition = repository.get_definition(candidate.experiment_id)
    if baseline_definition is None or candidate_definition is None:
        raise HTTPException(status_code=404, detail="Experiment definition not found")
    decision = decide_promotion(
        baseline,
        baseline_definition,
        candidate,
        candidate_definition,
        decided_by=user.user_id,
        now=datetime.now(UTC),
    )
    try:
        repository.save_decision(decision)
    except ExperimentConflict as exc:
        raise HTTPException(status_code=409, detail="Decision already exists") from exc
    return _json(decision)


@router.get("/api/feedback-candidates")
def list_feedback_candidates(
    confirmed: bool | None = Query(default=None),
    repository: PostgresExperimentRepository = Depends(get_experiment_repository),
    user: AuthenticatedUser = Depends(require_admin),
) -> list[dict]:
    del user
    return [
        _json(item) for item in repository.list_feedback_candidates(confirmed=confirmed)
    ]


@router.post("/api/feedback-candidates/{candidate_id}/confirm")
def confirm_feedback_candidate(
    candidate_id: str,
    request: FeedbackConfirmationRequest,
    service: FeedbackService = Depends(get_feedback_service),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    try:
        item = service.confirm(
            candidate_id,
            request.classification,
            request.include_in_gold,
            user,
            datetime.now(UTC),
        )
    except ExperimentNotFound as exc:
        raise HTTPException(
            status_code=404, detail="Feedback candidate not found"
        ) from exc
    except ExperimentConflict as exc:
        raise HTTPException(status_code=409, detail="Feedback conflict") from exc
    return _json(item)
