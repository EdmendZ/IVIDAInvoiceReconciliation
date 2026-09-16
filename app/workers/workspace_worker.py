"""Automatic workspace synchronization and preview computation."""
from __future__ import annotations

import logging
import threading

from app.domain.workspace import MatchStatus, TickSummary, WorkspaceScopeKey
from app.services.workspace_comparison import compare_workspace
from app.services.workspace_matching import select_candidates
from app.services.workspace_ports import WorkspaceRepository


logger = logging.getLogger(__name__)


class WorkspaceWorker:
    """Poll sources and compute previews without holding repository locks."""

    def __init__(
        self,
        repository: WorkspaceRepository,
        scope: WorkspaceScopeKey,
    ) -> None:
        self._repository = repository
        self._scope = scope

    def tick(self) -> TickSummary:
        sync = self._repository.sync_sources(self._scope)
        saved = discarded = errors = 0

        for preview_input in self._repository.pending_previews(self._scope, limit=100):
            try:
                proposal = select_candidates(
                    preview_input.invoice,
                    preview_input.receivings,
                    preview_input.used_ids,
                )
                if preview_input.manual_selection_ids is not None:
                    # A user's explicit selection remains authoritative even when
                    # a selected source is no longer present in the ready snapshot.
                    proposal.selected_document_ids = sorted(
                        preview_input.manual_selection_ids
                    )
                    proposal.status = MatchStatus.SELECTED

                selected_ids = set(proposal.selected_document_ids)
                selected = [
                    receiving
                    for receiving in preview_input.receivings
                    if receiving.document_id in selected_ids
                ]
                result = (
                    compare_workspace(preview_input.invoice, selected)
                    if proposal.selected_document_ids
                    else None
                )
                if self._repository.save_preview(
                    self._scope, preview_input, proposal, result
                ):
                    saved += 1
                else:
                    discarded += 1
            except Exception:
                errors += 1
                logger.exception(
                    "Workspace preview computation failed",
                    extra={"document_id": preview_input.invoice.document_id},
                )

        return TickSummary(
            synced=sync.changed_documents,
            previews_saved=saved,
            previews_discarded=discarded,
            errors=errors,
        )

    def run_forever(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Workspace synchronization tick failed")
            stop_event.wait(3)
