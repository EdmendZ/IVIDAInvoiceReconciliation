from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.auth_dependencies import require_admin
from app.api.dependencies import get_experiment_repository, get_feedback_service
from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.evaluation.models import EvaluationSummary
from app.experiments.domain import (
    DatasetIdentity,
    EvaluationRun,
    EvaluationRunStatus,
    ExperimentDefinition,
    ExperimentRole,
    ExperimentThresholds,
    FeedbackCandidate,
    FeedbackClassification,
)
from app.infra.postgres_experiment_repository import ExperimentConflict
from app.main import app


NOW = datetime(2026, 8, 7, tzinfo=UTC)
ADMIN = AuthenticatedUser(user_id="admin-1", username="admin", role=AdminRole.ADMIN)


def _definition(identifier: str, role: ExperimentRole) -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_id=identifier,
        name=role.value,
        role=role,
        manifest_path="evaluation_data/manifest.json",
        dataset_identity=DatasetIdentity(
            version="1.0.0",
            manifest_sha256="a" * 64,
            document_sha256s=("b" * 64,),
        ),
        parser_provider="mineru",
        parser_model="vlm",
        parser_version="1",
        normalizer_provider="openai-compatible",
        normalizer_model="model",
        prompt_version="prompt",
        schema_version="schema",
        parameters={},
        thresholds=ExperimentThresholds(),
        created_by="admin-1",
        created_at=NOW,
    )


def _summary(name: str, accuracy: str) -> EvaluationSummary:
    value = Decimal(accuracy)
    return EvaluationSummary(
        variant_name=name,
        document_count=1,
        schema_valid_rate=Decimal("1"),
        field_micro_accuracy=value,
        line_item_f1=value,
        evidence_coverage=value,
        p50_latency_ms=1,
        p95_latency_ms=1,
        parser_cache_hits=1,
    )


class Repository:
    def __init__(self) -> None:
        self.definitions = {
            "baseline": _definition("baseline", ExperimentRole.BASELINE),
            "candidate": _definition("candidate", ExperimentRole.CANDIDATE),
        }
        self.runs = {
            "run-a": EvaluationRun(
                run_id="run-a",
                experiment_id="baseline",
                status=EvaluationRunStatus.COMPLETED,
                summary=_summary("baseline", "0.95"),
                created_at=NOW,
                completed_at=NOW,
            ),
            "run-b": EvaluationRun(
                run_id="run-b",
                experiment_id="candidate",
                status=EvaluationRunStatus.COMPLETED,
                summary=_summary("candidate", "0.98"),
                created_at=NOW,
                completed_at=NOW,
            ),
        }
        self.decisions = []

    def create_definition(self, definition):
        self.definitions[definition.experiment_id] = definition
        return definition

    def list_definitions(self):
        return list(self.definitions.values())

    def get_definition(self, identifier):
        return self.definitions.get(identifier)

    def list_runs(self, experiment_id=None):
        values = list(self.runs.values())
        return (
            [item for item in values if item.experiment_id == experiment_id]
            if experiment_id
            else values
        )

    def get_run(self, identifier):
        return self.runs.get(identifier)

    def save_decision(self, decision):
        self.decisions.append(decision)
        return decision

    def list_feedback_candidates(self, *, confirmed=None):
        del confirmed
        return []


def _client(repository: Repository) -> TestClient:
    app.dependency_overrides[get_experiment_repository] = lambda: repository
    app.dependency_overrides[require_admin] = lambda: ADMIN
    return TestClient(app)


def _payload() -> dict:
    return {
        "name": "new candidate",
        "role": "candidate",
        "manifest_path": "evaluation_data/manifest.json",
        "dataset_identity": {
            "version": "1.0.0",
            "manifest_sha256": "a" * 64,
            "document_sha256s": ["b" * 64],
        },
        "parser_provider": "mineru",
        "parser_model": "vlm",
        "parser_version": "1",
        "normalizer_provider": "openai-compatible",
        "normalizer_model": "model",
        "prompt_version": "prompt",
        "schema_version": "schema",
        "thresholds": {},
    }


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_reviewer_cannot_create_experiment() -> None:
    def forbidden():
        raise HTTPException(status_code=403, detail="Admin role required")

    app.dependency_overrides[require_admin] = forbidden
    response = TestClient(app).post("/api/experiments", json=_payload())
    assert response.status_code == 403


def test_admin_creates_server_owned_definition() -> None:
    repository = Repository()
    response = _client(repository).post("/api/experiments", json=_payload())

    assert response.status_code == 201
    assert response.json()["created_by"] == ADMIN.user_id
    assert response.json()["experiment_id"] in repository.definitions


def test_malformed_threshold_is_rejected() -> None:
    payload = _payload()
    payload["thresholds"] = {"minimum_field_accuracy": 2}
    response = _client(Repository()).post("/api/experiments", json=payload)
    assert response.status_code == 422


def test_missing_experiment_and_run_return_404() -> None:
    client = _client(Repository())
    assert client.get("/api/experiments/missing").status_code == 404
    assert client.get("/api/experiment-runs/missing").status_code == 404


def test_admin_compares_completed_runs_without_external_provider() -> None:
    repository = Repository()
    response = _client(repository).post(
        "/api/promotion-decisions",
        json={"baseline_run_id": "run-a", "candidate_run_id": "run-b"},
    )

    assert response.status_code == 201
    assert response.json()["outcome"] == "recommended"
    assert len(repository.decisions) == 1


def test_definition_conflict_returns_409() -> None:
    class ConflictingRepository(Repository):
        def create_definition(self, definition):
            raise ExperimentConflict(definition.experiment_id)

    assert (
        _client(ConflictingRepository())
        .post("/api/experiments", json=_payload())
        .status_code
        == 409
    )


def test_admin_confirms_feedback_with_server_actor() -> None:
    class Feedback:
        def __init__(self) -> None:
            self.user = None

        def confirm(
            self, candidate_id, classification, include_in_gold, user, confirmed_at
        ):
            self.user = user
            return FeedbackCandidate(
                candidate_id=candidate_id,
                task_id="task-1",
                draft_id="draft-1",
                version_id="version-1",
                action_id="action-1",
                run_id="run-1",
                field_path="document_number",
                old_value="INV-1",
                new_value="INV-01",
                document_type="invoice",
                normalizer_model="model",
                prompt_version="prompt",
                classification=classification,
                include_in_gold=include_in_gold
                and classification == FeedbackClassification.MODEL_ERROR,
                confirmed_by=user.user_id,
                confirmed_at=confirmed_at,
                created_at=NOW,
            )

    service = Feedback()
    client = _client(Repository())
    app.dependency_overrides[get_feedback_service] = lambda: service

    response = client.post(
        "/api/feedback-candidates/feedback-1/confirm",
        json={"classification": "acceptable_variant", "include_in_gold": True},
    )

    assert response.status_code == 200
    assert response.json()["include_in_gold"] is False
    assert service.user == ADMIN
