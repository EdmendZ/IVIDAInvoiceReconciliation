"""ExtractionRun 的 PostgreSQL 状态机与 Worker 领取实现。"""

from datetime import UTC, datetime
from decimal import Decimal

from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.infra.database_models import ExtractionRunRow


class PostgresExtractionRunRepository:
    """用条件查询、行锁和短租约协调持久化异步任务。"""

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
        """原子领取一条到期且租约空闲的 Run。"""

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
            # PostgreSQL 中锁住候选行并跳过其他 Worker 已锁定的任务。
            # SQLite 测试环境没有等价语义，因此只验证单 Worker 行为。
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            row = session.execute(statement).scalar_one_or_none()
            if row is None:
                return None
            # 租约允许 Worker 崩溃后任务重新可领取；当前 Pilot 尚无 fencing token。
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
        """释放租约并把 Run 安排到未来，避免 Worker 忙等远端 API。"""

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
        normalization_latency_ms: int,
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
            normalization_latency_ms=normalization_latency_ms,
            completed_at=datetime.now(UTC),
            error_message=None,
            phase_error_code=None,
            lease_owner=None,
            lease_expires_at=None,
        )

    def set_model_provenance(
        self,
        run_id: str,
        *,
        parser_provider: str,
        parser_model: str,
        normalizer_provider: str,
        normalizer_model: str,
        prompt_version: str,
    ) -> None:
        self._update(
            run_id,
            parser_provider=parser_provider,
            parser_model=parser_model,
            normalizer_provider=normalizer_provider,
            normalizer_model=normalizer_model,
            prompt_version=prompt_version,
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

    def request_cancel(
        self,
        run_id: str,
        *,
        requested_by: str,
        requested_at: datetime,
    ) -> ExtractionRun | None:
        """幂等记录取消；queued 可立即完成，活动阶段等待 Worker 边界。"""

        with self._session_factory() as session:
            row = session.get(ExtractionRunRow, run_id)
            if row is None:
                return None
            if row.status == ExtractionRunStatus.CANCELLED.value:
                return self._to_domain(row)
            active = {
                ExtractionRunStatus.QUEUED.value,
                ExtractionRunStatus.SUBMITTING.value,
                ExtractionRunStatus.PARSING.value,
                ExtractionRunStatus.NORMALIZING.value,
                ExtractionRunStatus.VALIDATING.value,
            }
            if row.status not in active:
                return self._to_domain(row)
            # 保留第一次取消请求的主体和时间，重复点击不会覆盖审计信息。
            row.cancel_requested_at = row.cancel_requested_at or requested_at
            row.cancel_requested_by = row.cancel_requested_by or requested_by
            if row.status == ExtractionRunStatus.QUEUED.value:
                row.status = ExtractionRunStatus.CANCELLED.value
                row.cancel_completed_at = requested_at
                row.cancelled_stage = ExtractionRunStatus.QUEUED.value
                row.completed_at = requested_at
                row.lease_owner = None
                row.lease_expires_at = None
            session.commit()
            session.refresh(row)
            return self._to_domain(row)

    def is_cancel_requested(self, run_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(ExtractionRunRow, run_id)
            return bool(row and row.cancel_requested_at is not None)

    def mark_cancelled(
        self,
        run_id: str,
        *,
        stage: str,
        remote_may_continue: bool,
    ) -> ExtractionRun | None:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            row = session.get(ExtractionRunRow, run_id)
            if row is None:
                return None
            if row.status != ExtractionRunStatus.CANCELLED.value:
                row.status = ExtractionRunStatus.CANCELLED.value
                row.cancel_completed_at = now
                row.cancelled_stage = stage
                row.remote_may_continue = remote_may_continue
                row.completed_at = now
                row.lease_owner = None
                row.lease_expires_at = None
                session.commit()
                session.refresh(row)
            return self._to_domain(row)

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
