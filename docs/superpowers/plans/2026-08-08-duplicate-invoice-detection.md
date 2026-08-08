# Duplicate Invoice Detection Implementation Plan

> **Execution constraint:** Superpowers was used only to clarify requirements and write this plan. Do not invoke Superpowers to generate, edit, or review implementation code. Execute the tasks below with the repository's normal TDD workflow.

**Goal:** Add store-scoped uploads, exact-file idempotency, deterministic suspected-duplicate detection, reviewer resolution, approval gates, and end-to-end store isolation.

**Architecture:** Introduce a lightweight Tenant/Store registry and explicit access scope, then attach every new Task and Version to an internal Store. Keep exact-file identity separate from business duplicate assessments. Duplicate assessments are append-only, revisioned review artifacts; approval is allowed only after the latest assessment has a valid resolution and is committed atomically with its audit actions.

**Tech stack:** Python 3.11, FastAPI, Pydantic, SQLAlchemy 2, PostgreSQL, Alembic, MinIO, pytest, React 19, TypeScript, TanStack Query, Vitest.

**Source of truth:** `docs/superpowers/specs/2026-08-07-duplicate-invoice-detection-design.md`.

## Execution rules

- Work on `codex/duplicate-invoice-design`; keep each task as a reviewable commit.
- Write the named failing test first, run it, and confirm the failure is caused by missing behavior before implementation.
- Do not infer a Store for historical records. Use `legacy_unknown` assignments and keep approved Versions immutable.
- Never authorize by filtering only in the browser. Every list and direct-object API must apply the server-side Store scope.
- Return `404` for an out-of-scope object and `403` for a known Store the user cannot choose.
- Keep `external_store_id`/`external_tenant_id` as integration audit fields and use `store_id` for the internal FK.
- Use deterministic rules only. No LLM prompt, embedding, fuzzy model, or background auto-resolution belongs in this change.
- Before each commit, run the task-specific tests. Before the PR, run all verification commands in Task 12.

## Domain contracts used throughout the plan

Create these contracts once and reuse them rather than passing unrelated primitives between layers:

```python
class ScopeStatus(StrEnum):
    KNOWN = "known"
    LEGACY_UNKNOWN = "legacy_unknown"

@dataclass(frozen=True)
class StoreQueryScope:
    all_stores: bool
    store_ids: frozenset[UUID]

    def allows(self, store_id: UUID) -> bool:
        return self.all_stores or store_id in self.store_ids

@dataclass(frozen=True)
class UploadOutcome:
    task: ExtractionTask
    created: bool

class DuplicateResolution(StrEnum):
    CONFIRMED_DUPLICATE = "confirmed_duplicate"
    CONFIRMED_DISTINCT = "confirmed_distinct"
    REPLACEMENT = "replacement"
```

`StoreQueryScope(all_stores=True, store_ids=frozenset())` is the only representation of Admin-wide access. Never use `None` to mean unrestricted access.

## Task 1: Add the Tenant/Store registry and user scopes

**Files**

- Create: `app/domain/store_scopes.py`
- Modify: `app/infra/database_models.py`
- Create: `app/infra/postgres_store_repository.py`
- Create: `alembic/versions/20260808_15_add_store_scope_registry.py`
- Modify: `tests/fakes.py`
- Create: `tests/test_store_scopes.py`
- Create: `tests/test_postgres_store_repository.py`

### Steps

1. Add failing domain tests for:
   - Reviewer scope allows exactly assigned active Stores.
   - Admin scope allows every active Store.
   - Disabled Stores cannot be selected for new work.
   - Duplicate external `(external_tenant_id, external_store_id)` pairs are rejected.
2. Run `uv run pytest tests/test_store_scopes.py -q`; expect import/contract failures.
3. Add `BusinessTenant`, `BusinessStore`, `UserStoreScope`, `ScopeStatus`, and `StoreQueryScope` to `app/domain/store_scopes.py`. Validate nonblank names and enforce that a Reviewer scope is never silently treated as global.
4. Add ORM rows and migration tables:
   - `business_tenants(id, name, external_tenant_id, is_active, created_at, updated_at)`;
   - `business_stores(id, tenant_id, name, external_store_id, is_active, created_at, updated_at)`;
   - `user_store_scopes(user_id, store_id, created_at, created_by_user_id)`.
5. Add unique constraints for tenant external ID, tenant/store external pair, and user/store grant; add FKs and indexes on all lookup columns.
6. Implement `PostgresStoreRepository` methods:

```python
create_tenant(name, external_tenant_id, actor_user_id)
create_store(tenant_id, name, external_store_id, actor_user_id)
set_tenant_active(tenant_id, is_active)
set_store_active(store_id, is_active)
grant_user_store(user_id, store_id, actor_user_id)
revoke_user_store(user_id, store_id)
get_active_store(store_id)
resolve_active_store(external_tenant_id, external_store_id)
list_active_stores(query_scope)
scope_for_user(user: AuthenticatedUser) -> StoreQueryScope
```

7. Add repository integration tests for uniqueness, grant/revoke, disabled parent Tenant behavior, and Admin/Reviewer query scopes.
8. Run `uv run pytest tests/test_store_scopes.py tests/test_postgres_store_repository.py -q`; expect pass.
9. Run `uv run alembic upgrade head`; expect revision `20260808_15` applied.
10. Commit: `feat: add tenant and store scope registry`.

## Task 2: Expose Store administration and available-Store APIs

**Files**

- Create: `app/services/store_scope_service.py`
- Create: `app/api/store_routes.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/main.py`
- Create: `tests/test_store_scope_service.py`
- Create: `tests/test_store_api.py`
- Modify: `tests/test_route_governance.py`

### Steps

1. Add failing API tests for:
   - `GET /api/stores` returns active assigned Stores to Reviewer and all active Stores to Admin.
   - Reviewer receives `403` from all `/api/admin/tenants` and `/api/admin/stores` mutations.
   - Admin can create/disable Tenant and Store and grant/revoke a Reviewer scope.
   - Granting a disabled or nonexistent Store returns a stable validation error.
2. Run `uv run pytest tests/test_store_scope_service.py tests/test_store_api.py -q`; expect missing route/service failures.
3. Implement `StoreScopeService` as the only service that converts an authenticated user into `StoreQueryScope` and validates a selected Store. Required methods:

```python
query_scope_for(user)
require_selectable_store(user, store_id)
list_available_stores(user)
create_tenant/admin_create_store/set_active/grant/revoke
```

4. Add Pydantic request/response schemas. Use UUIDs for internal IDs and preserve external IDs as strings.
5. Add `store_routes.py` with Reviewer read route and Admin mutation routes. Wire dependencies and include the router in `app/main.py`.
6. Add stable errors: `store_not_found`, `store_access_denied`, `store_inactive`, `tenant_inactive`, `scope_conflict`.
7. Update route-governance expectations so every new Admin endpoint declares `require_admin`.
8. Run `uv run pytest tests/test_store_scope_service.py tests/test_store_api.py tests/test_route_governance.py -q`; expect pass.
9. Commit: `feat: add store scope administration api`.

## Task 3: Scope Tasks and Versions without mutating approved history

**Files**

- Modify: `app/domain/extraction_tasks.py`
- Modify: `app/domain/document_versions.py`
- Modify: `app/infra/database_models.py`
- Create: `alembic/versions/20260808_16_scope_documents_and_add_file_identity.py`
- Modify: `app/services/ports.py`
- Modify: `app/infra/postgres_task_repository.py`
- Modify: `app/infra/postgres_review_repository.py`
- Modify: `tests/fakes.py`
- Modify: `tests/test_postgres_task_repository.py`
- Modify: `tests/test_document_versions.py`

### Steps

1. Add failing tests that new Tasks and Versions persist `store_id` and `scope_status=known`, while legacy rows deserialize as `legacy_unknown` without inventing a Store.
2. Run `uv run pytest tests/test_postgres_task_repository.py tests/test_document_versions.py -q`; expect constructor/schema failures.
3. Add nullable `store_id` plus non-null `scope_status` to `extraction_tasks` and `document_versions`. New application writes must require `store_id`; database nullability exists only for legacy compatibility.
4. Add append-only `legacy_document_scope_assignments(document_kind, document_id, store_id, reason, assigned_by_user_id, assigned_at)` for explicit later remediation. Do not update an approved Version in place.
5. Add `document_file_identities(id, store_id, document_type, sha256, extraction_task_id, object_key, created_at)` with unique `(store_id, document_type, sha256)` and unique `extraction_task_id`.
6. Backfill existing Task/Version rows to `scope_status='legacy_unknown'`; do not assign a Store. Add checks ensuring `known` implies non-null `store_id`.
7. Extend domain mapping, ports, fakes, and PostgreSQL repositories with explicit `store_id` and `scope_status` fields.
8. Add migration upgrade/downgrade tests or repository roundtrip tests covering legacy rows and constraints.
9. Run `uv run pytest tests/test_postgres_task_repository.py tests/test_document_versions.py -q`; expect pass.
10. Run `uv run alembic upgrade head`; expect revision `20260808_16` applied.
11. Commit: `feat: attach store scope to document lifecycle`.

## Task 4: Make upload exact-file idempotency concurrent-safe

**Files**

- Modify: `app/services/document_upload_service.py`
- Modify: `app/services/ports.py`
- Modify: `app/infra/postgres_task_repository.py`
- Modify: `app/api/upload_routes.py`
- Modify: `tests/fakes.py`
- Modify: `tests/test_document_upload_service.py`
- Modify: `tests/test_upload_api.py`
- Create: `tests/test_postgres_upload_idempotency.py`

### Steps

1. Add failing service/API tests for:
   - Upload requires `store_id` and verifies user access.
   - First upload returns `UploadOutcome(created=True)` and HTTP `201`.
   - Same Store/type/hash returns the existing Task with `created=False` and HTTP `200`.
   - Same bytes in a different Store or document type create a new Task.
   - Existing failed Task is returned for its current retry flow; cancelled Task returns `task_cancelled_restore_required`.
   - Unauthorized Store returns `403`; unknown object lookup remains `404`.
2. Run `uv run pytest tests/test_document_upload_service.py tests/test_upload_api.py -q`; expect failure.
3. Change the upload signature to:

```python
upload(
    *, document_type, filename, data, store_id,
    actor: AuthenticatedUser, purchase_order_hint=None
) -> UploadOutcome
```

4. Add a repository operation that inserts Task and file identity in one DB transaction. On unique conflict, load and return the winning Task rather than translating it into `500`.
5. Preserve MinIO correctness:
   - derive a unique provisional object key;
   - if this request loses the DB identity race, delete only its own provisional object;
   - never delete the winner's object;
   - if DB insertion fails for another reason, remove the provisional object and re-raise.
6. Change upload route to accept mandatory multipart `store_id`, return a response with `task` and `created`, and select status `201`/`200` explicitly.
7. Add a real PostgreSQL concurrency test using two transactions/threads. Assert one identity, one Task, both callers receive the same Task ID, and only the winner object remains.
8. Run `uv run pytest tests/test_document_upload_service.py tests/test_upload_api.py tests/test_postgres_upload_idempotency.py -q`; expect pass.
9. Commit: `feat: enforce store scoped upload idempotency`.

## Task 5: Enforce Store isolation across existing backend flows

**Files**

- Modify: `app/api/upload_routes.py`
- Modify: `app/api/review_routes.py`
- Modify: `app/api/routes.py`
- Modify: `app/services/review_service.py`
- Modify: `app/services/reconciliation_application_service.py`
- Modify: `app/services/reconciliation_case_service.py`
- Modify: `app/infra/postgres_task_repository.py`
- Modify: `app/infra/postgres_review_repository.py`
- Modify: `app/infra/postgres_reconciliation_case_repository.py`
- Modify: `tests/test_upload_api.py`
- Modify: `tests/test_review_service.py`
- Modify: `tests/test_reconciliation_service.py`
- Modify: `tests/test_reconciliation_case_service.py`
- Modify: `tests/test_reconciliation_case_api.py`

### Steps

1. Add failing tests for two Reviewers assigned to disjoint Stores and one Admin. Cover task list/detail, review queue/detail/edit/reclassify/approve/reject, reconciliation candidates/compare, case list/detail/export/assignment.
2. Assert Reviewer A never sees Store B rows in lists and receives `404` for guessed Store B object IDs. Assert Admin sees both.
3. Assert Invoice and Receive Note can only be reconciled when both belong to the same known Store. Return `reconciliation_store_mismatch` otherwise.
4. Run the named tests; expect cross-Store leakage failures in current code.
5. Remove every `del user` in scoped routes. Resolve `StoreQueryScope` once at the service boundary and pass it to repository queries.
6. Add scoped repository methods rather than loading unrestricted rows and filtering in Python. Every SQL query must include either the explicit allowed Store IDs or the explicit Admin branch.
7. Treat `legacy_unknown` as Admin-only and exclude it from normal Reviewer queues and reconciliation candidates.
8. Apply scope to case assignment as an additional condition, not a replacement for existing role/assignee rules.
9. Run:

```text
uv run pytest tests/test_upload_api.py tests/test_review_service.py tests/test_reconciliation_service.py tests/test_reconciliation_case_service.py tests/test_reconciliation_case_api.py -q
```

   Expect pass.
10. Commit: `feat: enforce store isolation across review and reconciliation`.

## Task 6: Resolve Taptouch Receiving imports to internal Stores

**Files**

- Modify: `app/services/taptouch_receiving_import_service.py`
- Modify: `app/api/taptouch_integration_routes.py`
- Modify: `app/api/dependencies.py`
- Modify: `tests/test_taptouch_receiving_import.py`
- Modify: `tests/test_taptouch_integration_api.py`

### Steps

1. Add failing tests proving a machine principal's external tenant/store pair resolves to one active internal Store and the resulting Task/Version carries that `store_id`.
2. Add failures for unknown Store, inactive Store, inactive Tenant, and principal/store mismatch. Preserve the external IDs on the audit record.
3. Run `uv run pytest tests/test_taptouch_receiving_import.py tests/test_taptouch_integration_api.py -q`; expect missing resolver failures.
4. Inject the Store repository/resolver into the import service. Resolve before writing an object, Task, or Version so rejected requests leave no artifacts.
5. Keep existing machine credential authorization and add internal Store resolution as a second boundary.
6. Run the two tests again; expect pass.
7. Commit: `feat: map taptouch imports to internal stores`.

## Task 7: Implement pure deterministic duplicate rules

**Files**

- Create: `app/domain/duplicate_invoices.py`
- Create: `tests/test_duplicate_invoice_rules.py`

### Steps

1. Add table-driven failing tests for normalization and all rule boundaries from the design specification.
2. Required normalization assertions:
   - supplier business number removes formatting but preserves significant alphanumerics;
   - supplier name uses Unicode normalization, case folding, whitespace/punctuation normalization;
   - invoice number uppercases and removes Unicode whitespace plus `-`, `_`, `/`, `\\`, `.`;
   - currency uses uppercase ISO-like text and totals use exact decimal minor-unit semantics.
3. Required matching assertions:
   - candidate must be in the same Store and in approved/active-review status;
   - exact normalized invoice number plus supplier identity triggers strong evidence;
   - supplier, date, currency, and amount rule triggers standard evidence;
   - similar-number rule triggers only at normalized length `>= 6`, Levenshtein distance exactly `1`, and date distance `<= 30` days;
   - distance `0` is handled by exact rule, distance `2`, 31 days, different currency, and excluded status do not trigger;
   - comparisons are symmetric where the rule is intended to be symmetric.
4. Run `uv run pytest tests/test_duplicate_invoice_rules.py -q`; expect import failure.
5. Implement pure value objects and functions only:

```python
InvoiceDuplicateFacts
DuplicateSignal
DuplicateRuleResult
normalize_supplier_business_number(value: str | None) -> str | None
normalize_supplier_name(value: str | None) -> str | None
normalize_invoice_number(value: str | None) -> str | None
build_invoice_fingerprint(facts: InvoiceDuplicateFacts) -> str
evaluate_candidate(subject, candidate) -> DuplicateRuleResult | None
```

6. Keep rule codes and evidence values stable and serializable; never emit only a score without the matched fields.
7. Run `uv run pytest tests/test_duplicate_invoice_rules.py -q`; expect pass.
8. Commit: `feat: add deterministic duplicate invoice rules`.

## Task 8: Persist revisioned assessments, candidates, actions, and relationships

**Files**

- Modify: `app/infra/database_models.py`
- Create: `app/infra/postgres_duplicate_invoice_repository.py`
- Modify: `app/services/ports.py`
- Create: `alembic/versions/20260808_17_add_duplicate_assessments.py`
- Modify: `tests/fakes.py`
- Create: `tests/test_postgres_duplicate_invoice_repository.py`

### Steps

1. Add failing repository tests for append-only assessment revisions, candidate evidence, optimistic revision checks, immutable actions, and unique replacement/duplicate relationships.
2. Run `uv run pytest tests/test_postgres_duplicate_invoice_repository.py -q`; expect missing model/repository failures.
3. Add tables matching the design:
   - `duplicate_assessments` with subject Version, Store, revision, status, fingerprint, resolution, reason, resolved candidate, actor, and timestamps;
   - `duplicate_candidates` with assessment, candidate Version, rule code, evidence JSON, and deterministic ordering;
   - `duplicate_actions` append-only audit records containing before/after status, revision, actor, reason, and timestamp;
   - `invoice_relationships` for `confirmed_duplicate` and `replacement` links without modifying the old Version.
4. Add uniqueness and checks: one revision number per subject Version; one candidate per assessment/candidate Version; resolution/reason consistency; same-Store FK validation in repository transaction.
5. Add a PostgreSQL trigger that rejects UPDATE/DELETE on `duplicate_actions`.
6. Implement repository methods:

```python
create_assessment(subject, fingerprint, candidates)
get_latest(subject_version_id, query_scope)
list_candidate_facts(store_id, exclude_version_id)
resolve(assessment_id, expected_revision, resolution, reason, candidate_version_id, actor)
supersede_and_create(subject, expected_revision, fingerprint, candidates, actor)
```

7. Assert stale `expected_revision` produces domain `DuplicateAssessmentConflict` for API translation to `409`.
8. Run the repository tests and `uv run alembic upgrade head`; expect pass and revision `20260808_17`.
9. Commit: `feat: persist duplicate invoice assessments`.

## Task 9: Integrate assessment refresh, resolution, and atomic approval

**Files**

- Create: `app/services/duplicate_invoice_service.py`
- Modify: `app/services/review_service.py`
- Modify: `app/infra/postgres_review_repository.py`
- Modify: `app/infra/postgres_duplicate_invoice_repository.py`
- Modify: `app/api/review_routes.py`
- Modify: `app/api/dependencies.py`
- Create: `tests/test_duplicate_invoice_service.py`
- Modify: `tests/test_review_service.py`
- Create: `tests/test_postgres_duplicate_approval.py`

### Steps

1. Add failing service tests for:
   - starting Invoice review creates an assessment; Receive Note does not;
   - editing/reclassifying relevant Invoice fields supersedes the old assessment and creates a new revision;
   - `confirmed_duplicate` ends review and creates a relationship;
   - `confirmed_distinct` and `replacement` require nonblank reason and permit later approval;
   - replacement requires one selected candidate;
   - unresolved, stale, or newly changed candidate state blocks approval;
   - a clean assessment permits approval.
2. Add failing PostgreSQL tests that inject a failure after the Version status update and prove Version approval, review action, duplicate action, and relationship all roll back together.
3. Run the three named test files; expect missing service and non-atomic approval failures.
4. Implement `DuplicateInvoiceService`:

```python
refresh_for_version(version_id, actor, query_scope)
get_latest(version_id, query_scope)
resolve(version_id, expected_revision, resolution, reason, candidate_version_id, actor, query_scope)
assert_approvable(version_id, expected_revision, query_scope)
```

5. Refresh only when fields used by the fingerprint/rules change. Persist all evidence needed to explain the decision.
6. Replace the current separate `approve()` then `append_action()` path with one PostgreSQL transaction method that locks the latest Version and assessment, rechecks Store activity and candidate state, then writes:
   - approved Version/Task state;
   - review approval action;
   - duplicate resolution/approval action;
   - optional invoice relationship.
7. Make the in-memory fake expose the same atomic interface so unit tests do not encode a weaker contract.
8. Extend review detail response with latest assessment, candidates, evidence, resolution, reason, and revision.
9. Add `POST /api/reviews/{version_id}/duplicate-resolution`; require `expected_revision`, resolution, reason, and optional candidate ID. Translate stale revision to `409 duplicate_assessment_stale`.
10. Require approval request to carry the displayed `duplicate_assessment_revision` for Invoice. Return stable gates: `duplicate_review_required`, `duplicate_resolution_required`, `duplicate_assessment_stale`, `duplicate_candidate_changed`.
11. Run all three test files; expect pass.
12. Commit: `feat: gate invoice approval on duplicate resolution`.

## Task 10: Add Store selection and duplicate handling to the frontend

**Files**

- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/upload/UploadPage.tsx`
- Modify: `frontend/src/upload/taskPresentation.ts`
- Create: `frontend/src/upload/UploadPage.test.tsx`
- Create: `frontend/src/review/DuplicateRiskPanel.tsx`
- Create: `frontend/src/review/DuplicateRiskPanel.test.tsx`
- Modify: `frontend/src/review/ReviewDocumentPage.tsx`
- Create: `frontend/src/review/ReviewDocumentPage.test.tsx`
- Modify: `frontend/src/styles.css`

### Steps

1. Add failing UI tests for mandatory Store selection, first upload, exact duplicate replay, suspected candidate display, evidence labels, three resolutions, required reason, stale refresh, and disabled approval.
2. Run `npm test -- --run` from `frontend`; expect component/test failures.
3. Add typed client methods for available Stores, upload response `{task, created}`, review detail assessment, resolution command, and revision-aware approval.
4. Add Store selector to Upload. Disable submission until an active Store is selected. If `created=false`, show that the existing Task was reused and navigate to it without presenting success as a new upload.
5. Implement `DuplicateRiskPanel` with:
   - risk status and deterministic signal labels;
   - candidate invoice number, supplier, date, currency, total, and Version link;
   - radio/select control for the three resolutions;
   - candidate selection for duplicate/replacement where required;
   - mandatory reason and explicit save action;
   - stale/conflict message that refetches current assessment.
6. Disable Invoice approval until the latest displayed assessment is clean or resolved. Pass its revision in the approval request.
7. Keep backend validation authoritative; map stable error codes to concise user actions.
8. Run `npm test -- --run` and `npm run typecheck`; expect pass.
9. Commit: `feat: add duplicate review workflow to console`.

## Task 11: Add lightweight Admin Store management UI

**Files**

- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/app/App.tsx`
- Create: `frontend/src/admin/StoreAdminPage.tsx`
- Create: `frontend/src/admin/StoreAdminPage.test.tsx`
- Modify: `frontend/src/styles.css`

### Steps

1. Add failing tests that Admin can list/create/disable Tenants and Stores and grant/revoke Reviewer scope; Reviewer cannot see the Admin navigation item.
2. Run `npm test -- --run`; expect missing page failures.
3. Add typed Admin API calls and an `/admin/stores` route guarded by the authenticated role.
4. Build a compact page with Tenant/Store status, external IDs, and Reviewer assignments. Require confirmation before disabling an active Store; do not add bulk editing.
5. Show API constraint errors without optimistic state divergence, then refetch the affected list.
6. Run `npm test -- --run` and `npm run typecheck`; expect pass.
7. Commit: `feat: add admin store scope console`.

## Task 12: Document, migrate, and verify the complete workflow

**Files**

- Modify: `README.md`
- Modify: `.env.example`
- Modify: `docs/business-flow.md` if present; otherwise create `docs/duplicate-invoice-workflow.md`
- Modify: relevant files under `docs/reference/` required by documentation-sync tests
- Modify: `tests/test_documentation_sync.py`
- Modify: `tests/test_demo_business_flow.py`

### Steps

1. Add/extend the demo business-flow test to cover:
   - Admin creates Tenant/Store and assigns Reviewer;
   - Reviewer uploads Invoice into assigned Store;
   - exact replay returns the same Task;
   - extracted Invoice finds a suspected duplicate;
   - unresolved approval is blocked;
   - Reviewer records `confirmed_distinct` or `replacement` with reason;
   - approval succeeds and audit history remains visible;
   - another Store's Reviewer cannot observe any object in the flow.
2. Run `uv run pytest tests/test_demo_business_flow.py tests/test_documentation_sync.py -q`; expect the new behavior/docs assertions to fail before updates.
3. Document the business purpose, role responsibilities, exact versus suspected duplicate behavior, three resolutions, legacy unknown handling, migration order, local seed/setup, and recovery for failed/cancelled exact replays.
4. Document stable API error codes and make clear that `confirmed_duplicate` does not delete the historical invoice and `replacement` does not automatically void it.
5. Run migration roundtrip against a disposable PostgreSQL database:

```text
uv run alembic upgrade head
uv run alembic downgrade 20260807_14
uv run alembic upgrade head
```

   Expect all three commands to succeed and data-preserving downgrade limitations to be documented.
6. Run backend verification:

```text
uv run pytest -q
```

   Expect all tests pass.
7. Run frontend verification from `frontend`:

```text
npm test -- --run
npm run typecheck
npm run build
```

   Expect all commands pass.
8. Run Compose smoke test with PostgreSQL and MinIO, seed one Admin/Reviewer/Store, and manually verify upload replay plus duplicate approval gate. Record the exact seed command in README; do not commit credentials or generated objects.
9. Inspect `git diff --check` and `git status --short`; expect no whitespace errors and only intended changes.
10. Commit: `docs: explain duplicate invoice workflow`.

## Pull request acceptance checklist

- New Invoice and external Receive Note records always resolve to one active internal Store.
- Reviewer lists and direct-object APIs cannot disclose another Store's existence; Admin retains full access.
- Exact same Store/type/hash creates one Task and one durable MinIO object under concurrency.
- Business duplicate decisions remain explainable, deterministic, revisioned, and auditable.
- No Invoice can be approved against an unresolved or stale latest assessment.
- Approval and all related audit/relationship writes are one PostgreSQL transaction.
- Approved historical Versions remain immutable; legacy data is never assigned a guessed Store.
- Reconciliation and case flows enforce the same Store boundary.
- Backend suite, frontend tests/typecheck/build, Alembic roundtrip, and Compose smoke test pass.
- PR description links both this plan and the approved design specification.

## Recommended delivery sequence after this plan

Implement Tasks 1-6 as the Store boundary foundation, Tasks 7-9 as the duplicate decision backend, and Tasks 10-12 as UI, documentation, and release verification. Do not split the Store foundation and approval gate into independently deployable production releases unless the intermediate release keeps all new scoped behavior disabled, because a partially enforced Store boundary would create misleading security guarantees.
