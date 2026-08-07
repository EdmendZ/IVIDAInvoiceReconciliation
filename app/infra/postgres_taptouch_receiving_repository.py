"""Atomic, idempotent persistence for Taptouch receiving versions."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.document_versions import DocumentVersion
from app.infra.database_models import DocumentVersionRow
from app.services.taptouch_receiving_import_service import (
    ReceivingIdentityConflict,
    ReceivingImportOutcome,
    ReceivingVersionConflict,
)


class PostgresTaptouchReceivingRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def import_version(self, version: DocumentVersion) -> ReceivingImportOutcome:
        with self._session_factory() as session:
            existing = self._versions_for_identity(session, version, lock=True)
            outcome = self._decide(existing, version)
            if outcome is not None:
                return outcome
            session.add(DocumentVersionRow(**version.model_dump(mode="python")))
            try:
                session.commit()
                return ReceivingImportOutcome(version=version, created=True)
            except IntegrityError:
                session.rollback()
                raced = self._versions_for_identity(session, version, lock=False)
                outcome = self._decide(raced, version)
                if outcome is not None:
                    return outcome
                raise

    @staticmethod
    def _versions_for_identity(
        session: Session, version: DocumentVersion, *, lock: bool
    ) -> list[DocumentVersion]:
        statement = (
            select(DocumentVersionRow)
            .where(
                DocumentVersionRow.source_system == version.source_system,
                DocumentVersionRow.external_tenant_id == version.external_tenant_id,
                DocumentVersionRow.external_store_id == version.external_store_id,
                DocumentVersionRow.external_receiving_id
                == version.external_receiving_id,
            )
            .order_by(DocumentVersionRow.external_version.desc())
        )
        if lock:
            statement = statement.with_for_update()
        rows = session.execute(statement).scalars()
        return [PostgresTaptouchReceivingRepository._to_version(row) for row in rows]

    @classmethod
    def _decide(
        cls, existing: list[DocumentVersion], incoming: DocumentVersion
    ) -> ReceivingImportOutcome | None:
        if not existing:
            return None
        incoming_number = incoming.external_version
        assert incoming_number is not None
        latest_number = existing[0].external_version
        assert latest_number is not None
        if incoming_number < latest_number:
            raise ReceivingVersionConflict(
                f"External version {incoming_number} is older than {latest_number}"
            )
        same = next(
            (item for item in existing if item.external_version == incoming_number),
            None,
        )
        if same is not None:
            if cls._semantic_snapshot(same) == cls._semantic_snapshot(incoming):
                return ReceivingImportOutcome(version=same, created=False)
            raise ReceivingIdentityConflict(
                f"External version {incoming_number} already has different content"
            )
        return None

    @staticmethod
    def _semantic_snapshot(version: DocumentVersion) -> dict[str, Any]:
        data = version.model_dump(
            mode="json",
            exclude={
                "version_id",
                "approved_at",
                "created_at",
                "integration_principal",
            },
        )
        for field in ("upstream_updated_at",):
            value = getattr(version, field)
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                data[field] = value.astimezone(UTC).isoformat()
        return data

    @staticmethod
    def _to_version(row: DocumentVersionRow) -> DocumentVersion:
        return DocumentVersion.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in DocumentVersionRow.__table__.columns
            }
        )
