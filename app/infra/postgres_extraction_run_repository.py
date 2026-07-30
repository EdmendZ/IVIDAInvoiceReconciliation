from datetime import UTC, datetime
from decimal import Decimal

from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.infra.database_models import ExtractionRunRow


class PostgresExtractionRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, run: ExtractionRun) -> None:
        row = ExtractionRunRow(**run.model_dump(mode="python"))
        with self._session_factory() as session:
            session.add(row)
            session.commit()

    def get(self, run_id: str) -> ExtractionRun | None:
        with self._session_factory() as session:
            row = session.get(ExtractionRunRow, run_id)
            if row is None:
                return None
            return ExtractionRun.model_validate(
                {
                    column.name: getattr(row, column.name)
                    for column in ExtractionRunRow.__table__.columns
                }
            )

    def get_latest_for_task(self, task_id: str) -> ExtractionRun | None:
        with self._session_factory() as session:
            row = session.execute(
                select(ExtractionRunRow)
                .where(ExtractionRunRow.task_id == task_id)
                .order_by(ExtractionRunRow.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            return self._to_domain(row) if row else None

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> ExtractionRun | None:
        eligible = (
            ExtractionRunStatus.QUEUED.value,
            ExtractionRunStatus.PARSING.value,
            ExtractionRunStatus.NORMALIZING.value,
            ExtractionRunStatus.VALIDATING.value,
        )
        with self._session_factory() as session:
            statement = (
                select(ExtractionRunRow)
                .where(
                    ExtractionRunRow.status.in_(eligible),
                    or_(
                        ExtractionRunRow.next_attempt_at.is_(None),
                        ExtractionRunRow.next_attempt_at <= now,
                    ),
                    or_(
                        ExtractionRunRow.lease_expires_at.is_(None),
                        ExtractionRunRow.lease_expires_at < now,
                    ),
                )
                .order_by(ExtractionRunRow.created_at)
                .limit(1)
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            row = session.execute(statement).scalar_one_or_none()
            if row is None:
                return None
            row.lease_owner = worker_id
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            session.commit()
            return self._to_domain(row)

    def set_remote_job(
        self,
        run_id: str,
        *,
        remote_job_id: str,
        next_attempt_at: datetime,
    ) -> None:
        self._update(
            run_id,
            status=ExtractionRunStatus.PARSING.value,
            remote_job_id=remote_job_id,
            next_attempt_at=next_attempt_at,
            attempt_count=0,
            lease_owner=None,
            lease_expires_at=None,
        )

    def schedule_poll(
        self,
        run_id: str,
        *,
        next_attempt_at: datetime,
        increment_attempt: bool = False,
    ) -> None:
        with self._session_factory() as session:
            values: dict = {
                "status": ExtractionRunStatus.PARSING.value,
                "next_attempt_at": next_attempt_at,
                "lease_owner": None,
                "lease_expires_at": None,
            }
            if increment_attempt:
                row = session.get(ExtractionRunRow, run_id)
                if row is None:
                    return
                values["attempt_count"] = row.attempt_count + 1
            session.execute(
                update(ExtractionRunRow)
                .where(ExtractionRunRow.run_id == run_id)
                .values(**values)
            )
            session.commit()

    def set_status(
        self,
        run_id: str,
        status: ExtractionRunStatus,
        *,
        release_lease: bool = True,
    ) -> None:
        values: dict = {"status": status.value}
        if release_lease:
            values.update(lease_owner=None, lease_expires_at=None)
        self._update(run_id, **values)

    def mark_ready_for_review(
        self,
        run_id: str,
        *,
        normalized_output: dict,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_cost_aud: str | None,
    ) -> None:
        self._update(
            run_id,
            status=ExtractionRunStatus.READY_FOR_REVIEW.value,
            normalized_output=normalized_output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_aud=(
                Decimal(estimated_cost_aud)
                if estimated_cost_aud is not None
                else None
            ),
            completed_at=datetime.now(UTC),
            error_message=None,
            phase_error_code=None,
            lease_owner=None,
            lease_expires_at=None,
        )

    def complete(
        self,
        run_id: str,
        *,
        raw_output: dict,
        normalized_output: dict,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_cost_aud: str | None,
    ) -> None:
        with self._session_factory() as session:
            session.execute(
                update(ExtractionRunRow)
                .where(ExtractionRunRow.run_id == run_id)
                .values(
                    status=ExtractionRunStatus.SUCCEEDED.value,
                    raw_output=raw_output,
                    normalized_output=normalized_output,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost_aud=(
                        Decimal(estimated_cost_aud)
                        if estimated_cost_aud is not None
                        else None
                    ),
                    completed_at=datetime.now(UTC),
                    error_message=None,
                )
            )
            session.commit()

    def fail(
        self,
        run_id: str,
        error_message: str,
        *,
        error_code: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            session.execute(
                update(ExtractionRunRow)
                .where(ExtractionRunRow.run_id == run_id)
                .values(
                    status=ExtractionRunStatus.FAILED.value,
                    error_message=error_message,
                    phase_error_code=error_code,
                    completed_at=datetime.now(UTC),
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
            session.commit()

    def _update(self, run_id: str, **values) -> None:
        with self._session_factory() as session:
            session.execute(
                update(ExtractionRunRow)
                .where(ExtractionRunRow.run_id == run_id)
                .values(**values)
            )
            session.commit()

    @staticmethod
    def _to_domain(row: ExtractionRunRow) -> ExtractionRun:
        return ExtractionRun.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in ExtractionRunRow.__table__.columns
            }
        )
