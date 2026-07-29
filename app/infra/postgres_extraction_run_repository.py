from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import update
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

    def fail(self, run_id: str, error_message: str) -> None:
        with self._session_factory() as session:
            session.execute(
                update(ExtractionRunRow)
                .where(ExtractionRunRow.run_id == run_id)
                .values(
                    status=ExtractionRunStatus.FAILED.value,
                    error_message=error_message,
                    completed_at=datetime.now(UTC),
                )
            )
            session.commit()
