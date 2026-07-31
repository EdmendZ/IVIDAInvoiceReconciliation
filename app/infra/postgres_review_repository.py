"""人工审核 Version 与追加式 Action 的 PostgreSQL 实现。"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.domain.document_versions import (
    DocumentVersion,
    DocumentVersionStatus,
    ReviewAction,
)
from app.infra.database_models import DocumentVersionRow, ReviewActionRow


class ApprovedVersionImmutable(RuntimeError):
    pass


class ReviewVersionNotFound(LookupError):
    pass


class PostgresReviewRepository:
    """持久化不可覆盖的版本快照与审核动作。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_version(
        self,
        *,
        task_id: str,
        source_draft_id: str,
        document_type: str,
        document_json: dict,
        created_by: str,
    ) -> DocumentVersion:
        """为 Task 创建下一个版本号。

        当前 max+1 依赖唯一约束检测并发冲突，符合单审核人 Pilot；高并发环境
        应增加任务级锁、序列化事务或唯一冲突重试。
        """

        with self._session_factory() as session:
            current = session.execute(
                select(func.max(DocumentVersionRow.version_number)).where(
                    DocumentVersionRow.task_id == task_id
                )
            ).scalar_one()
            version = DocumentVersion(
                version_id=str(uuid4()),
                task_id=task_id,
                source_draft_id=source_draft_id,
                version_number=(current or 0) + 1,
                document_type=document_type,
                document_json=document_json,
                status=DocumentVersionStatus.DRAFT,
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
            session.add(DocumentVersionRow(**version.model_dump(mode="python")))
            session.commit()
            return version

    def get_version(self, version_id: str) -> DocumentVersion | None:
        with self._session_factory() as session:
            row = session.get(DocumentVersionRow, version_id)
            return self._to_version(row) if row else None

    def get_latest_version(self, task_id: str) -> DocumentVersion | None:
        with self._session_factory() as session:
            row = session.execute(
                select(DocumentVersionRow)
                .where(DocumentVersionRow.task_id == task_id)
                .order_by(DocumentVersionRow.version_number.desc())
                .limit(1)
            ).scalar_one_or_none()
            return self._to_version(row) if row else None

    def get_approved_version(self, version_id: str) -> DocumentVersion | None:
        with self._session_factory() as session:
            row = session.execute(
                select(DocumentVersionRow).where(
                    DocumentVersionRow.version_id == version_id,
                    DocumentVersionRow.status
                    == DocumentVersionStatus.APPROVED.value,
                )
            ).scalar_one_or_none()
            return self._to_version(row) if row else None

    def list_versions(
        self,
        *,
        status: DocumentVersionStatus | None = None,
    ) -> list[DocumentVersion]:
        with self._session_factory() as session:
            statement = select(DocumentVersionRow)
            if status is not None:
                statement = statement.where(
                    DocumentVersionRow.status == status.value
                )
            rows = session.execute(
                statement.order_by(DocumentVersionRow.created_at.desc())
            ).scalars()
            return [self._to_version(row) for row in rows]

    def approve(self, version_id: str, user_id: str) -> DocumentVersion:
        """只允许 draft -> approved 的单向条件更新。"""

        now = datetime.now(UTC)
        with self._session_factory() as session:
            # 状态写入 WHERE：并发重复批准时最多一个事务更新成功。
            result = session.execute(
                update(DocumentVersionRow)
                .where(
                    DocumentVersionRow.version_id == version_id,
                    DocumentVersionRow.status
                    == DocumentVersionStatus.DRAFT.value,
                )
                .values(
                    status=DocumentVersionStatus.APPROVED.value,
                    approved_by=user_id,
                    approved_at=now,
                )
            )
            if result.rowcount != 1:
                raise ApprovedVersionImmutable(version_id)
            session.commit()
        version = self.get_version(version_id)
        if version is None:
            raise ReviewVersionNotFound(version_id)
        return version

    def reject(self, version_id: str) -> DocumentVersion:
        """只允许 draft -> rejected，已批准/驳回版本保持不可变。"""

        with self._session_factory() as session:
            result = session.execute(
                update(DocumentVersionRow)
                .where(
                    DocumentVersionRow.version_id == version_id,
                    DocumentVersionRow.status
                    == DocumentVersionStatus.DRAFT.value,
                )
                .values(status=DocumentVersionStatus.REJECTED.value)
            )
            if result.rowcount != 1:
                raise ApprovedVersionImmutable(version_id)
            session.commit()
        version = self.get_version(version_id)
        if version is None:
            raise ReviewVersionNotFound(version_id)
        return version

    def append_action(
        self,
        *,
        version_id: str,
        actor_user_id: str,
        action: str,
        field_path: str | None = None,
        old_value=None,
        new_value=None,
        reason: str | None = None,
    ) -> ReviewAction:
        """追加一条审计动作；不修改或折叠历史 Action。"""

        item = ReviewAction(
            action_id=str(uuid4()),
            version_id=version_id,
            actor_user_id=actor_user_id,
            action=action,
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            created_at=datetime.now(UTC),
        )
        with self._session_factory() as session:
            session.add(ReviewActionRow(**item.model_dump(mode="python")))
            session.commit()
        return item

    def list_actions(self, version_id: str) -> list[ReviewAction]:
        with self._session_factory() as session:
            rows = session.execute(
                select(ReviewActionRow)
                .where(ReviewActionRow.version_id == version_id)
                .order_by(ReviewActionRow.created_at)
            ).scalars()
            return [
                ReviewAction.model_validate(
                    {
                        column.name: getattr(row, column.name)
                        for column in ReviewActionRow.__table__.columns
                    }
                )
                for row in rows
            ]

    @staticmethod
    def _to_version(row: DocumentVersionRow) -> DocumentVersion:
        return DocumentVersion.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in DocumentVersionRow.__table__.columns
            }
        )
