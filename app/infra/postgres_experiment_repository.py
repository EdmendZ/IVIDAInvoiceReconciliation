"""SQLAlchemy persistence for extraction experiments and decisions."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.evaluation.models import DocumentEvaluation, EvaluationSummary
from app.experiments.domain import (
    ErrorSlice,
    EvaluationRun,
    ExperimentDefinition,
    FeedbackCandidate,
    FeedbackClassification,
    PromotionDecision,
)
from app.infra.database_models import (
    EvaluationRunRow,
    ExperimentDefinitionRow,
    FeedbackCandidateRow,
    PromotionDecisionRow,
)


class ExperimentConflict(RuntimeError):
    pass


class ExperimentTransitionError(RuntimeError):
    pass


class ExperimentNotFound(LookupError):
    pass


class PostgresExperimentRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def create_definition(
        self, definition: ExperimentDefinition
    ) -> ExperimentDefinition:
        json_data = definition.model_dump(mode="json")
        row = ExperimentDefinitionRow(
            experiment_id=definition.experiment_id,
            name=definition.name,
            role=definition.role.value,
            manifest_path=definition.manifest_path,
            dataset_identity=json_data["dataset_identity"],
            parser_provider=definition.parser_provider,
            parser_model=definition.parser_model,
            parser_version=definition.parser_version,
            normalizer_provider=definition.normalizer_provider,
            normalizer_model=definition.normalizer_model,
            prompt_version=definition.prompt_version,
            schema_version=definition.schema_version,
            parameters=json_data["parameters"],
            thresholds=json_data["thresholds"],
            created_by=definition.created_by,
            created_at=definition.created_at,
        )
        try:
            with self._factory() as session:
                session.add(row)
                session.commit()
        except IntegrityError as exc:
            raise ExperimentConflict(definition.experiment_id) from exc
        return definition

    def get_definition(self, experiment_id: str) -> ExperimentDefinition | None:
        with self._factory() as session:
            row = session.get(ExperimentDefinitionRow, experiment_id)
            return self._definition(row) if row else None

    def list_definitions(self) -> list[ExperimentDefinition]:
        with self._factory() as session:
            rows = session.execute(
                select(ExperimentDefinitionRow).order_by(
                    ExperimentDefinitionRow.created_at.desc()
                )
            ).scalars()
            return [self._definition(row) for row in rows]

    def create_run(self, run: EvaluationRun) -> EvaluationRun:
        row = EvaluationRunRow(
            run_id=run.run_id,
            experiment_id=run.experiment_id,
            status=run.status.value,
            summary=run.summary.model_dump(mode="json") if run.summary else None,
            documents=[item.model_dump(mode="json") for item in run.documents],
            slices=[item.model_dump(mode="json") for item in run.slices],
            error_code=run.error_code,
            error_message=run.error_message,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            cancelled_at=run.cancelled_at,
        )
        try:
            with self._factory() as session:
                session.add(row)
                session.commit()
        except IntegrityError as exc:
            raise ExperimentConflict(run.run_id) from exc
        return run

    def _transition(
        self, run_id: str, expected: tuple[str, ...], **values
    ) -> EvaluationRun:
        with self._factory() as session:
            result = session.execute(
                update(EvaluationRunRow)
                .where(
                    EvaluationRunRow.run_id == run_id,
                    EvaluationRunRow.status.in_(expected),
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise ExperimentTransitionError(run_id)
            session.commit()
        run = self.get_run(run_id)
        if run is None:
            raise ExperimentNotFound(run_id)
        return run

    def mark_run_running(self, run_id: str, *, started_at: datetime) -> EvaluationRun:
        return self._transition(
            run_id, ("queued",), status="running", started_at=started_at
        )

    def complete_run(
        self,
        run_id: str,
        *,
        summary: EvaluationSummary,
        documents: list[DocumentEvaluation],
        slices: list[ErrorSlice],
        completed_at: datetime,
    ) -> EvaluationRun:
        if summary.document_count != len(documents):
            raise ValueError("summary document_count must include every document")
        return self._transition(
            run_id,
            ("running",),
            status="completed",
            summary=summary.model_dump(mode="json"),
            documents=[item.model_dump(mode="json") for item in documents],
            slices=[item.model_dump(mode="json") for item in slices],
            completed_at=completed_at,
        )

    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
        completed_at: datetime,
    ) -> EvaluationRun:
        return self._transition(
            run_id,
            ("queued", "running"),
            status="failed",
            error_code=error_code,
            error_message=error_message,
            completed_at=completed_at,
        )

    def cancel_run(self, run_id: str, *, cancelled_at: datetime) -> EvaluationRun:
        return self._transition(
            run_id, ("queued", "running"), status="cancelled", cancelled_at=cancelled_at
        )

    def get_run(self, run_id: str) -> EvaluationRun | None:
        with self._factory() as session:
            row = session.get(EvaluationRunRow, run_id)
            return self._run(row) if row else None

    def list_runs(self, experiment_id: str | None = None) -> list[EvaluationRun]:
        with self._factory() as session:
            statement = select(EvaluationRunRow)
            if experiment_id:
                statement = statement.where(
                    EvaluationRunRow.experiment_id == experiment_id
                )
            rows = session.execute(
                statement.order_by(EvaluationRunRow.created_at.desc())
            ).scalars()
            return [self._run(row) for row in rows]

    def create_feedback_candidates(
        self, candidates: list[FeedbackCandidate]
    ) -> list[FeedbackCandidate]:
        with self._factory() as session:
            for item in candidates:
                data = item.model_dump(mode="json")
                session.add(
                    FeedbackCandidateRow(
                        candidate_id=item.candidate_id,
                        payload=data,
                        classification=data["classification"],
                        include_in_gold=item.include_in_gold,
                        confirmed_by=item.confirmed_by,
                        confirmed_at=item.confirmed_at,
                        created_at=item.created_at,
                    )
                )
            session.commit()
        return candidates

    def list_feedback_candidates(
        self, *, confirmed: bool | None = None
    ) -> list[FeedbackCandidate]:
        with self._factory() as session:
            statement = select(FeedbackCandidateRow)
            if confirmed is True:
                statement = statement.where(
                    FeedbackCandidateRow.confirmed_at.is_not(None)
                )
            if confirmed is False:
                statement = statement.where(FeedbackCandidateRow.confirmed_at.is_(None))
            rows = session.execute(
                statement.order_by(FeedbackCandidateRow.created_at.desc())
            ).scalars()
            return [self._feedback(row) for row in rows]

    def confirm_feedback(
        self,
        candidate_id: str,
        *,
        classification: FeedbackClassification,
        include_in_gold: bool,
        confirmed_by: str,
        confirmed_at: datetime,
    ) -> FeedbackCandidate:
        eligible = (
            include_in_gold and classification == FeedbackClassification.MODEL_ERROR
        )
        with self._factory() as session:
            row = session.get(FeedbackCandidateRow, candidate_id)
            if row is None:
                raise ExperimentNotFound(candidate_id)
            if row.confirmed_at is not None:
                raise ExperimentConflict(candidate_id)
            payload = dict(row.payload)
            payload.update(
                classification=classification.value,
                include_in_gold=eligible,
                confirmed_by=confirmed_by,
                confirmed_at=confirmed_at.isoformat(),
            )
            row.payload = payload
            row.classification = classification.value
            row.include_in_gold = eligible
            row.confirmed_by = confirmed_by
            row.confirmed_at = confirmed_at
            session.commit()
            return self._feedback(row)

    def save_decision(self, decision: PromotionDecision) -> PromotionDecision:
        with self._factory() as session:
            session.add(
                PromotionDecisionRow(
                    decision_id=decision.decision_id,
                    baseline_run_id=decision.baseline_run_id,
                    candidate_run_id=decision.candidate_run_id,
                    outcome=decision.outcome.value,
                    payload=decision.model_dump(mode="json"),
                    decided_by=decision.decided_by,
                    decided_at=decision.decided_at,
                )
            )
            session.commit()
        return decision

    def get_decision(self, decision_id: str) -> PromotionDecision | None:
        with self._factory() as session:
            row = session.get(PromotionDecisionRow, decision_id)
            return PromotionDecision.model_validate(row.payload) if row else None

    @staticmethod
    def _definition(row: ExperimentDefinitionRow) -> ExperimentDefinition:
        return ExperimentDefinition.model_validate(
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
        )

    @staticmethod
    def _run(row: EvaluationRunRow) -> EvaluationRun:
        return EvaluationRun.model_validate(
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
        )

    @staticmethod
    def _feedback(row: FeedbackCandidateRow) -> FeedbackCandidate:
        return FeedbackCandidate.model_validate(row.payload)
