from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.parse_results import ParseResultRecord
from app.infra.database_models import ParseResultRow


class PostgresParseResultRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, result: ParseResultRecord) -> None:
        with self._session_factory() as session:
            session.add(ParseResultRow(**result.model_dump(mode="python")))
            session.commit()

    def get_for_run(self, run_id: str) -> ParseResultRecord | None:
        with self._session_factory() as session:
            row = session.execute(
                select(ParseResultRow).where(ParseResultRow.run_id == run_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            return ParseResultRecord.model_validate(
                {
                    column.name: getattr(row, column.name)
                    for column in ParseResultRow.__table__.columns
                }
            )
