"""ParseResultRecord 的 PostgreSQL Repository。"""

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.parse_results import ParseResultRecord
from app.infra.database_models import ParseResultRow


class PostgresParseResultRepository:
    """按 Run 保存/读取可复用 MinerU 文本结果。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, result: ParseResultRecord) -> None:
        """保存解析文本和产物位置；每个 Run 最多对应一份解析记录。"""
        with self._session_factory() as session:
            session.add(ParseResultRow(**result.model_dump(mode="python")))
            session.commit()

    def get_for_run(self, run_id: str) -> ParseResultRecord | None:
        """读取可供归一化阶段恢复使用的 MinerU 结果。"""
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
