"""Atomic workspace use cases implemented by PostgresWorkspaceRepository."""
from typing import Protocol

from app.domain.workspace import (
    ActionPage, CachedResponse, ConfirmationPage, ConfirmationQuery,
    ConfirmationView, DocumentDetail, DocumentPage, DocumentQuery,
    IntakeResponse, MatchProposal, PreparedUpload, PreviewInput, PreviewResult,
    RuntimeView, SourceMetadata, SyncSummary, WorkspaceCommand,
    WorkspaceMutationResponse, WorkspaceOperation, WorkspaceScopeKey,
)


class WorkspaceRepository(Protocol):
    def cached_request(self, scope: WorkspaceScopeKey, actor_id: str, key: str,
                       request_hash: str) -> CachedResponse | None: ...

    def intake(self, scope: WorkspaceScopeKey, prepared: PreparedUpload, actor_id: str,
               key: str, request_hash: str) -> IntakeResponse: ...

    def list_documents(self, scope: WorkspaceScopeKey, query: DocumentQuery) -> DocumentPage: ...

    def get_document(self, scope: WorkspaceScopeKey, document_id: str) -> DocumentDetail: ...

    def get_actions(self, scope: WorkspaceScopeKey, document_id: str,
                    page: int, page_size: int) -> ActionPage: ...

    def list_confirmations(self, scope: WorkspaceScopeKey,
                           query: ConfirmationQuery) -> ConfirmationPage: ...

    def mutate(self, scope: WorkspaceScopeKey, document_id: str,
               operation: WorkspaceOperation, command: WorkspaceCommand,
               actor_id: str, key: str, request_hash: str) -> WorkspaceMutationResponse: ...

    def get_confirmation(self, scope: WorkspaceScopeKey, confirmation_id: str) -> ConfirmationView: ...

    def source_metadata(self, scope: WorkspaceScopeKey, document_id: str) -> SourceMetadata: ...

    def sync_sources(self, scope: WorkspaceScopeKey) -> SyncSummary: ...

    def pending_previews(self, scope: WorkspaceScopeKey, limit: int = 100) -> list[PreviewInput]: ...

    def save_preview(self, scope: WorkspaceScopeKey, input: PreviewInput,
                     proposal: MatchProposal, result: PreviewResult | None) -> bool: ...

    def runtime(self, scope: WorkspaceScopeKey) -> RuntimeView: ...
