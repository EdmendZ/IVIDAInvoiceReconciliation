"""Record the authenticated integration principal for upstream versions.

Revision ID: 20260807_14
Revises: 20260807_13
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_14"
down_revision: str | None = "20260807_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SOURCE_SHAPE_WITH_PRINCIPAL = """
(source_kind IN ('invoice_upload', 'external_receive_note_upload')
 AND ((source_kind = 'invoice_upload' AND document_type = 'invoice')
      OR (source_kind = 'external_receive_note_upload'
          AND document_type = 'receive_note'))
 AND task_id IS NOT NULL AND source_draft_id IS NOT NULL
 AND version_number IS NOT NULL AND created_by IS NOT NULL
 AND source_system IS NULL AND integration_principal IS NULL
 AND external_tenant_id IS NULL AND external_brand_id IS NULL
 AND external_store_id IS NULL AND external_supplier_id IS NULL
 AND external_receiving_id IS NULL AND external_version IS NULL
 AND record_status IS NULL AND upstream_updated_at IS NULL
 AND ((status = 'approved' AND trust_method = 'human_approved')
      OR (status <> 'approved' AND trust_method = 'untrusted')))
OR
(source_kind = 'taptouch_receiving' AND document_type = 'receive_note'
 AND task_id IS NULL AND source_draft_id IS NULL
 AND version_number IS NULL AND created_by IS NULL AND approved_by IS NULL
 AND source_system = 'taptouch' AND integration_principal IS NOT NULL
 AND external_tenant_id IS NOT NULL AND external_store_id IS NOT NULL
 AND external_supplier_id IS NOT NULL AND external_receiving_id IS NOT NULL
 AND external_version IS NOT NULL AND record_status IN ('active', 'voided')
 AND external_version >= 1 AND upstream_updated_at IS NOT NULL
 AND approved_at IS NOT NULL AND status = 'approved'
 AND trust_method = 'upstream_authoritative')
"""

SOURCE_SHAPE_WITHOUT_PRINCIPAL = """
(source_kind IN ('invoice_upload', 'external_receive_note_upload')
 AND ((source_kind = 'invoice_upload' AND document_type = 'invoice')
      OR (source_kind = 'external_receive_note_upload'
          AND document_type = 'receive_note'))
 AND task_id IS NOT NULL AND source_draft_id IS NOT NULL
 AND version_number IS NOT NULL AND created_by IS NOT NULL
 AND source_system IS NULL AND external_tenant_id IS NULL
 AND external_brand_id IS NULL AND external_store_id IS NULL
 AND external_supplier_id IS NULL AND external_receiving_id IS NULL
 AND external_version IS NULL AND record_status IS NULL
 AND upstream_updated_at IS NULL
 AND ((status = 'approved' AND trust_method = 'human_approved')
      OR (status <> 'approved' AND trust_method = 'untrusted')))
OR
(source_kind = 'taptouch_receiving' AND document_type = 'receive_note'
 AND task_id IS NULL AND source_draft_id IS NULL
 AND version_number IS NULL AND created_by IS NULL AND approved_by IS NULL
 AND source_system = 'taptouch' AND external_tenant_id IS NOT NULL
 AND external_store_id IS NOT NULL AND external_supplier_id IS NOT NULL
 AND external_receiving_id IS NOT NULL AND external_version IS NOT NULL
 AND record_status IN ('active', 'voided') AND external_version >= 1
 AND upstream_updated_at IS NOT NULL AND approved_at IS NOT NULL
 AND status = 'approved' AND trust_method = 'upstream_authoritative')
"""


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("integration_principal", sa.String(length=255), nullable=True),
    )
    # Approved snapshots are update-protected. Backfill the pre-auth-scope rows
    # inside the migration transaction, then immediately restore protection.
    op.execute(
        "ALTER TABLE document_versions "
        "DISABLE TRIGGER protect_approved_document_versions"
    )
    op.execute(
        "UPDATE document_versions "
        "SET integration_principal = 'legacy-integration-token' "
        "WHERE source_kind = 'taptouch_receiving'"
    )
    op.execute(
        "ALTER TABLE document_versions "
        "ENABLE TRIGGER protect_approved_document_versions"
    )
    op.drop_constraint(
        "ck_document_versions_source_shape",
        "document_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_versions_source_shape",
        "document_versions",
        SOURCE_SHAPE_WITH_PRINCIPAL,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_versions_source_shape",
        "document_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_versions_source_shape",
        "document_versions",
        SOURCE_SHAPE_WITHOUT_PRINCIPAL,
    )
    op.drop_column("document_versions", "integration_principal")
