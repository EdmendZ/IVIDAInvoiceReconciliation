"""Add Taptouch receiving provenance to canonical document versions.

Revision ID: 20260807_13
Revises: 20260807_12
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_13"
down_revision: str | None = "20260807_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SOURCE_SHAPE = """
(source_kind IN ('invoice_upload', 'external_receive_note_upload')
 AND task_id IS NOT NULL AND source_draft_id IS NOT NULL
 AND version_number IS NOT NULL AND created_by IS NOT NULL
 AND source_system IS NULL AND external_tenant_id IS NULL
 AND external_brand_id IS NULL AND external_store_id IS NULL
 AND external_supplier_id IS NULL AND external_receiving_id IS NULL
 AND external_version IS NULL AND record_status IS NULL
 AND upstream_updated_at IS NULL)
OR
(source_kind = 'taptouch_receiving' AND document_type = 'receive_note'
 AND task_id IS NULL AND source_draft_id IS NULL
 AND version_number IS NULL AND created_by IS NULL AND approved_by IS NULL
 AND source_system = 'taptouch' AND external_tenant_id IS NOT NULL
 AND external_store_id IS NOT NULL AND external_supplier_id IS NOT NULL
 AND external_receiving_id IS NOT NULL AND external_version IS NOT NULL
 AND record_status IN ('active', 'voided') AND upstream_updated_at IS NOT NULL
 AND status = 'approved' AND trust_method = 'upstream_authoritative')
"""


def upgrade() -> None:
    columns = [
        sa.Column("source_kind", sa.String(length=64), nullable=True),
        sa.Column("trust_method", sa.String(length=64), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=True),
        sa.Column("external_tenant_id", sa.String(length=255), nullable=True),
        sa.Column("external_brand_id", sa.String(length=255), nullable=True),
        sa.Column("external_store_id", sa.String(length=255), nullable=True),
        sa.Column("external_supplier_id", sa.String(length=255), nullable=True),
        sa.Column("external_receiving_id", sa.String(length=255), nullable=True),
        sa.Column("external_version", sa.Integer(), nullable=True),
        sa.Column("record_status", sa.String(length=32), nullable=True),
        sa.Column("upstream_updated_at", sa.DateTime(timezone=True), nullable=True),
    ]
    for column in columns:
        op.add_column("document_versions", column)

    op.execute(
        """
        UPDATE document_versions
        SET source_kind = CASE
                WHEN document_type = 'invoice' THEN 'invoice_upload'
                ELSE 'external_receive_note_upload'
            END,
            trust_method = CASE
                WHEN status = 'approved' THEN 'human_approved'
                ELSE 'untrusted'
            END
        """
    )
    op.alter_column("document_versions", "source_kind", nullable=False)
    op.alter_column("document_versions", "trust_method", nullable=False)
    for name in ("task_id", "source_draft_id", "version_number", "created_by"):
        op.alter_column("document_versions", name, nullable=True)

    op.create_unique_constraint(
        "uq_document_versions_external_version",
        "document_versions",
        [
            "source_system",
            "external_tenant_id",
            "external_store_id",
            "external_receiving_id",
            "external_version",
        ],
    )
    op.create_check_constraint(
        "ck_document_versions_source_kind",
        "document_versions",
        "source_kind IN ('invoice_upload', 'external_receive_note_upload', "
        "'taptouch_receiving')",
    )
    op.create_check_constraint(
        "ck_document_versions_trust_method",
        "document_versions",
        "trust_method IN ('human_approved', 'upstream_authoritative', 'untrusted')",
    )
    op.create_check_constraint(
        "ck_document_versions_source_shape",
        "document_versions",
        SOURCE_SHAPE,
    )


def downgrade() -> None:
    count = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM document_versions "
            "WHERE source_kind = 'taptouch_receiving'"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Export and remove Taptouch document versions before downgrading"
        )

    op.drop_constraint(
        "ck_document_versions_source_shape", "document_versions", type_="check"
    )
    op.drop_constraint(
        "ck_document_versions_trust_method", "document_versions", type_="check"
    )
    op.drop_constraint(
        "ck_document_versions_source_kind", "document_versions", type_="check"
    )
    op.drop_constraint(
        "uq_document_versions_external_version", "document_versions", type_="unique"
    )
    for name in ("task_id", "source_draft_id", "version_number", "created_by"):
        op.alter_column("document_versions", name, nullable=False)
    for name in (
        "upstream_updated_at",
        "record_status",
        "external_version",
        "external_receiving_id",
        "external_supplier_id",
        "external_store_id",
        "external_brand_id",
        "external_tenant_id",
        "source_system",
        "trust_method",
        "source_kind",
    ):
        op.drop_column("document_versions", name)
