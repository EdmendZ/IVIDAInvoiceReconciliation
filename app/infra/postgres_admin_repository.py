from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.admin_users import AdminSession, AdminUser, AuthenticatedUser
from app.infra.database_models import AdminSessionRow, AdminUserRow


class PostgresAdminRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_user(self, user: AdminUser) -> None:
        with self._session_factory() as session:
            session.add(AdminUserRow(**user.model_dump(mode="python")))
            session.commit()

    def get_user_by_username(self, username: str) -> AdminUser | None:
        with self._session_factory() as session:
            row = session.execute(
                select(AdminUserRow).where(AdminUserRow.username == username)
            ).scalar_one_or_none()
            return AdminUser.model_validate(row) if row else None

    def create_session(self, admin_session: AdminSession) -> None:
        with self._session_factory() as session:
            session.add(
                AdminSessionRow(**admin_session.model_dump(mode="python"))
            )
            session.commit()

    def get_session_user(
        self,
        token_hash: str,
        now: datetime,
    ) -> AuthenticatedUser | None:
        with self._session_factory() as session:
            row = session.execute(
                select(AdminUserRow)
                .join(
                    AdminSessionRow,
                    AdminSessionRow.user_id == AdminUserRow.user_id,
                )
                .where(
                    AdminSessionRow.session_token_hash == token_hash,
                    AdminSessionRow.expires_at > now,
                    AdminUserRow.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return AuthenticatedUser(
                user_id=row.user_id,
                username=row.username,
                role=row.role,
            )

    def delete_session(self, token_hash: str) -> None:
        with self._session_factory() as session:
            session.execute(
                delete(AdminSessionRow).where(
                    AdminSessionRow.session_token_hash == token_hash
                )
            )
            session.commit()
