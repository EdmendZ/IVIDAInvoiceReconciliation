"""Add immutable workspace history and atomic operational records.

Revision ID: 20260916_15
Revises: 20260807_14
"""
from alembic import op

revision = "20260916_15"
down_revision = "20260807_14"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE TABLE ws_documents (\n\tdocument_id TEXT NOT NULL, \n\ttenant_id TEXT NOT NULL, \n\tstore_id TEXT NOT NULL, \n\tdocument_type TEXT NOT NULL, \n\tsource_kind TEXT NOT NULL, \n\ttask_id TEXT, \n\tupstream_identity TEXT, \n\tcurrent_revision_id TEXT, \n\trevision INTEGER NOT NULL, \n\tprocessing_status TEXT NOT NULL, \n\treview_status TEXT, \n\tselected_document_ids JSONB NOT NULL, \n\tselection_origin TEXT, \n\tselection_note TEXT, \n\tmatch_status TEXT NOT NULL, \n\tcurrent_preview_id TEXT, \n\tpreview_stale BOOLEAN NOT NULL, \n\tcurrent_confirmation_id TEXT, \n\tsource_changed BOOLEAN NOT NULL, \n\terror_code TEXT, \n\tcreated_by TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (document_id), \n\tCONSTRAINT ck_ws_documents_type CHECK (document_type IN ('invoice','receive_note')), \n\tCONSTRAINT ck_ws_documents_source CHECK (source_kind IN ('upload','taptouch')), \n\tCONSTRAINT ck_ws_documents_processing CHECK (processing_status IN ('processing','ready','failed','cancelled','voided')), \n\tCONSTRAINT ck_ws_documents_review CHECK (review_status IN ('open','investigating','completed')), \n\tCONSTRAINT ck_ws_documents_selection CHECK (selection_origin IN ('automatic','manual')), \n\tCONSTRAINT ck_ws_documents_match CHECK (match_status IN ('waiting_counterpart','needs_selection','selected')), \n\tCONSTRAINT ck_ws_documents_revision CHECK (revision >= 1), \n\tCONSTRAINT ck_ws_documents_review_shape CHECK ((document_type = 'invoice' AND review_status IS NOT NULL) OR (document_type = 'receive_note' AND review_status IS NULL)), \n\tCONSTRAINT ck_ws_documents_source_shape CHECK ((source_kind = 'upload' AND task_id IS NOT NULL) OR (source_kind = 'taptouch' AND upstream_identity IS NOT NULL)), \n\tCONSTRAINT ck_ws_documents_ready CHECK (processing_status <> 'ready' OR current_revision_id IS NOT NULL), \n\tUNIQUE (task_id), \n\tFOREIGN KEY(task_id) REFERENCES extraction_tasks (task_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(created_by) REFERENCES admin_users (user_id) ON DELETE RESTRICT\n)")
    op.execute('CREATE INDEX ix_ws_documents_scope_type_status_updated ON ws_documents (tenant_id, store_id, document_type, processing_status, updated_at, document_id)')
    op.execute('CREATE UNIQUE INDEX uq_ws_documents_upstream ON ws_documents (tenant_id, store_id, upstream_identity) WHERE upstream_identity IS NOT NULL')
    op.execute("CREATE TABLE ws_revisions (\n\trevision_id TEXT NOT NULL, \n\tdocument_id TEXT NOT NULL, \n\tsequence INTEGER NOT NULL, \n\tsource_draft_id TEXT, \n\tsource_version_id TEXT, \n\tpayload JSONB NOT NULL, \n\tevidence JSONB NOT NULL, \n\tvalidation_issues JSONB NOT NULL, \n\tcontent_sha256 TEXT NOT NULL, \n\torigin TEXT NOT NULL, \n\tactor_id TEXT, \n\treason TEXT, \n\tevidence_origin_revision_id TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (revision_id), \n\tCONSTRAINT uq_ws_revisions_sequence UNIQUE (document_id, sequence), \n\tCONSTRAINT ck_ws_revisions_sequence CHECK (sequence >= 1), \n\tCONSTRAINT ck_ws_revisions_origin CHECK (origin IN ('extracted','manual','upstream')), \n\tCONSTRAINT ck_ws_revisions_source CHECK (source_draft_id IS NULL OR source_version_id IS NULL), \n\tFOREIGN KEY(document_id) REFERENCES ws_documents (document_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(source_draft_id) REFERENCES document_drafts (draft_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(source_version_id) REFERENCES document_versions (version_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_id) REFERENCES admin_users (user_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(evidence_origin_revision_id) REFERENCES ws_revisions (revision_id) ON DELETE RESTRICT\n)")
    op.execute("CREATE TABLE ws_previews (\n\tpreview_id TEXT NOT NULL, \n\tinvoice_document_id TEXT NOT NULL, \n\tinput_revision_ids JSONB NOT NULL, \n\tscope_generation BIGINT NOT NULL, \n\tselection_origin TEXT NOT NULL, \n\trule_version TEXT NOT NULL, \n\ttolerances JSONB NOT NULL, \n\tinput_sha256 TEXT NOT NULL, \n\tresult JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (preview_id), \n\tCONSTRAINT uq_ws_previews_input UNIQUE (invoice_document_id, input_sha256, rule_version), \n\tCONSTRAINT ck_ws_previews_selection CHECK (selection_origin IN ('automatic','manual')), \n\tCONSTRAINT ck_ws_previews_rule CHECK (rule_version = 'ir-simple-rules-1'), \n\tCONSTRAINT ck_ws_previews_generation CHECK (scope_generation >= 0), \n\tFOREIGN KEY(invoice_document_id) REFERENCES ws_documents (document_id) ON DELETE RESTRICT\n)")
    op.execute('CREATE INDEX ix_ws_previews_invoice_created ON ws_previews (invoice_document_id, created_at)')
    op.execute("CREATE TABLE ws_confirmations (\n\tconfirmation_id TEXT NOT NULL, \n\tinvoice_document_id TEXT NOT NULL, \n\tpreview_id TEXT NOT NULL, \n\tinvoice_revision_id TEXT NOT NULL, \n\treceive_revision_ids JSONB NOT NULL, \n\tresult_snapshot JSONB NOT NULL, \n\trule_version TEXT NOT NULL, \n\ttolerances JSONB NOT NULL, \n\tinput_sha256 TEXT NOT NULL, \n\tactor_id TEXT NOT NULL, \n\tresolution TEXT NOT NULL, \n\tnote TEXT, \n\tacknowledged_unverified_dimensions JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (confirmation_id), \n\tCONSTRAINT ck_ws_confirmations_resolution CHECK (resolution IN ('matched','resolved_with_note')), \n\tCONSTRAINT ck_ws_confirmations_rule CHECK (rule_version = 'ir-simple-rules-1'), \n\tFOREIGN KEY(invoice_document_id) REFERENCES ws_documents (document_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(preview_id) REFERENCES ws_previews (preview_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(invoice_revision_id) REFERENCES ws_revisions (revision_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_id) REFERENCES admin_users (user_id) ON DELETE RESTRICT\n)")
    op.execute('CREATE TABLE ws_claims (\n\treceive_document_id TEXT NOT NULL, \n\tinvoice_document_id TEXT NOT NULL, \n\tconfirmation_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (receive_document_id), \n\tFOREIGN KEY(receive_document_id) REFERENCES ws_documents (document_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(invoice_document_id) REFERENCES ws_documents (document_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(confirmation_id) REFERENCES ws_confirmations (confirmation_id) ON DELETE RESTRICT\n)')
    op.execute("CREATE TABLE ws_actions (\n\taction_id TEXT NOT NULL, \n\tdocument_id TEXT NOT NULL, \n\tactor_id TEXT, \n\taction TEXT NOT NULL, \n\treason TEXT, \n\told_revision INTEGER, \n\tnew_revision INTEGER NOT NULL, \n\tconfirmation_id TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (action_id), \n\tCONSTRAINT ck_ws_actions_action CHECK (action IN ('uploaded','extracted','edited','selection_changed','investigating','confirmed','reopened','voided','source_updated','retry_requested')), \n\tCONSTRAINT ck_ws_actions_revision CHECK (new_revision >= 1 AND (old_revision IS NULL OR old_revision >= 1)), \n\tFOREIGN KEY(document_id) REFERENCES ws_documents (document_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_id) REFERENCES admin_users (user_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(confirmation_id) REFERENCES ws_confirmations (confirmation_id) ON DELETE RESTRICT\n)")
    op.execute('CREATE INDEX ix_ws_actions_document_created ON ws_actions (document_id, created_at, action_id)')
    op.execute('CREATE TABLE ws_scopes (\n\tscope_id TEXT NOT NULL, \n\tgeneration BIGINT NOT NULL, \n\tlast_sync_at TIMESTAMP WITH TIME ZONE, \n\tlast_error_code TEXT, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (scope_id), \n\tCONSTRAINT ck_ws_scopes_generation CHECK (generation >= 0)\n)')
    op.execute('CREATE TABLE ws_requests (\n\tscope_id TEXT NOT NULL, \n\tactor_id TEXT NOT NULL, \n\tidempotency_key TEXT NOT NULL, \n\trequest_hash TEXT NOT NULL, \n\tresponse_status INTEGER NOT NULL, \n\tresponse_json JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (scope_id, actor_id, idempotency_key), \n\tFOREIGN KEY(scope_id) REFERENCES ws_scopes (scope_id) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_id) REFERENCES admin_users (user_id) ON DELETE RESTRICT\n)')
    op.execute('ALTER TABLE ws_documents ADD CONSTRAINT fk_ws_documents_current_confirmation_id FOREIGN KEY(current_confirmation_id) REFERENCES ws_confirmations (confirmation_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED')
    op.execute('ALTER TABLE ws_documents ADD CONSTRAINT fk_ws_documents_current_revision_id FOREIGN KEY(current_revision_id) REFERENCES ws_revisions (revision_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED')
    op.execute('ALTER TABLE ws_documents ADD CONSTRAINT fk_ws_documents_current_preview_id FOREIGN KEY(current_preview_id) REFERENCES ws_previews (preview_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED')
    op.execute("CREATE FUNCTION ws_reject_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$\nBEGIN RAISE EXCEPTION 'Workspace history is immutable' USING ERRCODE = '55000'; END;\n$$")
    op.execute('CREATE TRIGGER protect_ws_revisions BEFORE UPDATE OR DELETE ON ws_revisions FOR EACH ROW EXECUTE FUNCTION ws_reject_history_mutation()')
    op.execute('CREATE TRIGGER protect_ws_previews BEFORE UPDATE OR DELETE ON ws_previews FOR EACH ROW EXECUTE FUNCTION ws_reject_history_mutation()')
    op.execute('CREATE TRIGGER protect_ws_confirmations BEFORE UPDATE OR DELETE ON ws_confirmations FOR EACH ROW EXECUTE FUNCTION ws_reject_history_mutation()')
    op.execute('CREATE TRIGGER protect_ws_actions BEFORE UPDATE OR DELETE ON ws_actions FOR EACH ROW EXECUTE FUNCTION ws_reject_history_mutation()')


def downgrade():
    # A rollback is operationally a feature flag change; never erase history.
    connection = op.get_bind()
    for table in ("ws_documents", "ws_revisions", "ws_previews", "ws_confirmations",
                  "ws_claims", "ws_actions", "ws_scopes", "ws_requests"):
        if connection.exec_driver_sql(f"SELECT EXISTS (SELECT 1 FROM {table})").scalar():
            raise RuntimeError("Cannot downgrade a populated workspace")
    op.drop_constraint('fk_ws_documents_current_confirmation_id', "ws_documents", type_="foreignkey")
    op.drop_constraint('fk_ws_documents_current_revision_id', "ws_documents", type_="foreignkey")
    op.drop_constraint('fk_ws_documents_current_preview_id', "ws_documents", type_="foreignkey")
    op.drop_table('ws_requests')
    op.drop_table('ws_scopes')
    op.drop_table('ws_actions')
    op.drop_table('ws_claims')
    op.drop_table('ws_confirmations')
    op.drop_table('ws_previews')
    op.drop_table('ws_revisions')
    op.drop_table('ws_documents')
    op.execute("DROP FUNCTION ws_reject_history_mutation()")
