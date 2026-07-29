from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.document_drafts import DocumentDraft, DraftBundle
from app.domain.normalization import FieldEvidence
from app.domain.validation import ValidationIssue
from app.infra.database_models import (
    DocumentDraftRow,
    FieldEvidenceRow,
    ValidationIssueRow,
)


class PostgresDocumentDraftRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_with_evidence_and_issues(
        self,
        draft: DocumentDraft,
        evidence: list[FieldEvidence],
        issues: list[ValidationIssue],
    ) -> DocumentDraft:
        with self._session_factory() as session:
            session.add(DocumentDraftRow(**draft.model_dump(mode="python")))
            session.add_all(
                [
                    FieldEvidenceRow(
                        evidence_id=str(uuid4()),
                        draft_id=draft.draft_id,
                        **item.model_dump(mode="python"),
                    )
                    for item in evidence
                ]
            )
            session.add_all(
                [
                    ValidationIssueRow(
                        issue_id=str(uuid4()),
                        draft_id=draft.draft_id,
                        **item.model_dump(mode="python"),
                    )
                    for item in issues
                ]
            )
            session.commit()
        return draft

    def get_for_run(self, run_id: str) -> DraftBundle | None:
        with self._session_factory() as session:
            draft_row = session.execute(
                select(DocumentDraftRow).where(DocumentDraftRow.run_id == run_id)
            ).scalar_one_or_none()
            if draft_row is None:
                return None
            evidence_rows = session.execute(
                select(FieldEvidenceRow)
                .where(FieldEvidenceRow.draft_id == draft_row.draft_id)
                .order_by(FieldEvidenceRow.evidence_id)
            ).scalars()
            issue_rows = session.execute(
                select(ValidationIssueRow)
                .where(ValidationIssueRow.draft_id == draft_row.draft_id)
                .order_by(ValidationIssueRow.issue_id)
            ).scalars()
            return DraftBundle(
                draft=DocumentDraft.model_validate(
                    {
                        column.name: getattr(draft_row, column.name)
                        for column in DocumentDraftRow.__table__.columns
                    }
                ),
                evidence=[
                    FieldEvidence.model_validate(
                        {
                            field: getattr(row, field)
                            for field in FieldEvidence.model_fields
                        }
                    )
                    for row in evidence_rows
                ],
                issues=[
                    ValidationIssue.model_validate(
                        {
                            field: getattr(row, field)
                            for field in ValidationIssue.model_fields
                        }
                    )
                    for row in issue_rows
                ],
            )
