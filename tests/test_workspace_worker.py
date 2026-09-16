from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.workspace import PreviewInput, RevisionView, SyncSummary, WorkspaceScopeKey
from app.workers.workspace_worker import WorkspaceWorker


def revision(n: int, kind: str) -> RevisionView:
    return RevisionView(
        document_id=str(UUID(int=n)),
        revision_id=str(UUID(int=n + 1000)),
        sequence=1,
        origin="extracted" if kind == "invoice" else "upstream",
        payload={
            "document_type": kind,
            "document_number": f"DOC-{n}",
            "document_date": "2026-01-01",
            "purchase_order_number": "PO-1",
            "supplier": {"name": "Acme", "business_number": "12-34"},
            "items": [
                {
                    "description": "Rice",
                    "sku": "R1",
                    "unit": "bag",
                    "quantity": "10",
                    "unit_price": "2",
                    "line_total": "20",
                }
            ],
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def preview_input(n: int = 1, *, manual: list[str] | None = None) -> PreviewInput:
    return PreviewInput(
        invoice=revision(n, "invoice"),
        receivings=[revision(n + 100, "receive_note")],
        used_ids=set(),
        scope_generation=2,
        document_revision=3,
        manual_selection_ids=manual,
    )


class FakeRepository:
    def __init__(self, inputs, outcomes=None):
        self.inputs = inputs
        self.outcomes = iter(outcomes or [True] * len(inputs))
        self.calls = []

    def sync_sources(self, scope):
        self.calls.append(("sync", scope))
        return SyncSummary(changed_documents=2, scope_generation=2)

    def pending_previews(self, scope, limit=100):
        self.calls.append(("pending", scope, limit))
        return self.inputs

    def save_preview(self, scope, value, proposal, result):
        self.calls.append(("save", scope, value, proposal, result))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_tick_syncs_then_computes_and_cas_saves_at_most_100() -> None:
    repository = FakeRepository([preview_input()], [True])
    scope = WorkspaceScopeKey(tenant_id="tenant", store_id="store")

    summary = WorkspaceWorker(repository, scope).tick()

    assert summary.model_dump() == {
        "synced": 2,
        "previews_saved": 1,
        "previews_discarded": 0,
        "errors": 0,
    }
    assert [call[0] for call in repository.calls] == ["sync", "pending", "save"]
    assert repository.calls[1][2] == 100
    assert repository.calls[2][3].selected_document_ids == [
        repository.inputs[0].receivings[0].document_id
    ]
    assert repository.calls[2][4] is not None


def test_manual_selection_is_never_replaced_when_selected_source_is_unavailable() -> None:
    missing_id = str(UUID(int=999))
    value = preview_input(manual=[missing_id])
    repository = FakeRepository([value])

    WorkspaceWorker(
        repository, WorkspaceScopeKey(tenant_id="tenant", store_id="store")
    ).tick()

    _, _, _, proposal, result = repository.calls[-1]
    assert proposal.selected_document_ids == [missing_id]
    assert proposal.status == "selected"
    assert result is not None
    # The repository receives the missing ID and adds the stable SOURCE_VOIDED
    # blocker under its locked current-state checks.
    assert result.outcome == "difference"


def test_document_failure_is_isolated_and_later_documents_continue() -> None:
    repository = FakeRepository(
        [preview_input(1), preview_input(2)], [RuntimeError("boom"), False]
    )

    summary = WorkspaceWorker(
        repository, WorkspaceScopeKey(tenant_id="tenant", store_id="store")
    ).tick()

    assert summary.previews_saved == 0
    assert summary.previews_discarded == 1
    assert summary.errors == 1
    assert [call[0] for call in repository.calls].count("save") == 2


class OneTickEvent:
    def __init__(self):
        self.stopped = False
        self.waits = []

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.waits.append(seconds)
        self.stopped = True
        return True


def test_run_forever_uses_interruptible_fixed_three_second_wait() -> None:
    repository = FakeRepository([])
    event = OneTickEvent()

    WorkspaceWorker(
        repository, WorkspaceScopeKey(tenant_id="tenant", store_id="store")
    ).run_forever(event)

    assert event.waits == [3]
    assert [call[0] for call in repository.calls] == ["sync", "pending"]


def test_workspace_settings_default_disabled_and_scope_required_only_when_enabled(
    monkeypatch,
) -> None:
    defaults = Settings(_env_file=None)
    assert defaults.workspace_enabled is False
    assert defaults.workspace_poll_seconds == 3

    Settings(
        _env_file=None,
        workspace_enabled=True,
        workspace_tenant_id=" tenant ",
        workspace_store_id=" store ",
    )
    monkeypatch.setenv("WORKSPACE_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_TENANT_ID", "tenant")
    monkeypatch.setenv("WORKSPACE_STORE_ID", "store")
    monkeypatch.setenv("WORKSPACE_POLL_SECONDS", "3")
    assert Settings(_env_file=None).workspace_poll_seconds == 3
    monkeypatch.delenv("WORKSPACE_TENANT_ID")
    monkeypatch.delenv("WORKSPACE_STORE_ID")
    monkeypatch.delenv("WORKSPACE_ENABLED")
    monkeypatch.delenv("WORKSPACE_POLL_SECONDS")
    with pytest.raises(ValidationError, match="WORKSPACE_TENANT_ID"):
        Settings(_env_file=None, workspace_enabled=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, workspace_poll_seconds=4)


def test_worker_module_does_not_import_fastapi() -> None:
    from pathlib import Path

    source = Path("app/workers/workspace_worker.py").read_text(encoding="utf-8")
    assert "fastapi" not in source.casefold()
