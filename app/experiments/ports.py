"""Persistence ports for extraction quality experiments."""

from datetime import datetime
from typing import Protocol

from app.evaluation.models import DocumentEvaluation, EvaluationSummary
from app.experiments.domain import (
    ErrorSlice,
    EvaluationRun,
    ExperimentDefinition,
    FeedbackCandidate,
    FeedbackClassification,
    PromotionDecision,
)


class ExperimentRepository(Protocol):
    def create_definition(
        self, definition: ExperimentDefinition
    ) -> ExperimentDefinition: ...
    def get_definition(self, experiment_id: str) -> ExperimentDefinition | None: ...
    def list_definitions(self) -> list[ExperimentDefinition]: ...
    def create_run(self, run: EvaluationRun) -> EvaluationRun: ...
    def mark_run_running(
        self, run_id: str, *, started_at: datetime
    ) -> EvaluationRun: ...
    def complete_run(
        self,
        run_id: str,
        *,
        summary: EvaluationSummary,
        documents: list[DocumentEvaluation],
        slices: list[ErrorSlice],
        completed_at: datetime,
    ) -> EvaluationRun: ...
    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
        completed_at: datetime,
    ) -> EvaluationRun: ...
    def cancel_run(self, run_id: str, *, cancelled_at: datetime) -> EvaluationRun: ...
    def get_run(self, run_id: str) -> EvaluationRun | None: ...
    def list_runs(self, experiment_id: str | None = None) -> list[EvaluationRun]: ...
    def create_feedback_candidates(
        self, candidates: list[FeedbackCandidate]
    ) -> list[FeedbackCandidate]: ...
    def list_feedback_candidates(
        self, *, confirmed: bool | None = None
    ) -> list[FeedbackCandidate]: ...
    def confirm_feedback(
        self,
        candidate_id: str,
        *,
        classification: FeedbackClassification,
        include_in_gold: bool,
        confirmed_by: str,
        confirmed_at: datetime,
    ) -> FeedbackCandidate: ...
    def save_decision(self, decision: PromotionDecision) -> PromotionDecision: ...
    def get_decision(self, decision_id: str) -> PromotionDecision | None: ...
