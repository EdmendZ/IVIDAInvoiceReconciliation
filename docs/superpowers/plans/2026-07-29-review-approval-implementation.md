# Human Review and Reconciliation Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated human review, immutable approved document versions, complete audit history, and a hard gate that allows reconciliation only from approved versions.

**Architecture:** Build role-based session authentication, a transactional ReviewService, append-only document versions and review actions, then add a small React review application. Reconciliation accepts approved version IDs and persists a result linked to those immutable versions.

**Tech Stack:** Python 3.11, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Argon2, React, TypeScript, Vite, Vitest, Playwright.

## Global Constraints

- This plan starts only after the MinerU extraction plan completion gate passes.
- Every document is reviewed; there is no automatic approval.
- Roles are exactly `reviewer` and `admin`.
- Approved versions are immutable.
- Audit rows are append-only.
- Reconciliation rejects drafts, rejected versions and superseded unapproved versions.
- The review UI runs on port `5274`; the API remains on `8200`.
- Original files and MinerU artifacts remain private.

---

### Task 1: Add reviewer authentication and roles

**Files:**
- Modify: `pyproject.toml`
- Create: `app/domain/admin_users.py`
- Modify: `app/infra/database_models.py`
- Create: `app/infra/postgres_admin_repository.py`
- Create: `app/services/auth_service.py`
- Create: `app/api/auth_routes.py`
- Create: `app/api/auth_dependencies.py`
- Create: `app/cli/create_admin.py`
- Create: `migrations/versions/20260729_05_add_admin_users_and_sessions.py`
- Modify: `app/main.py`
- Test: `tests/test_auth_api.py`

**Interfaces:**
- Produces: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`.
- Produces: `require_reviewer()` and `require_admin()` dependencies.

- [ ] **Step 1: Write failing login and role tests**

```python
def test_reviewer_can_login(client, reviewer) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": "reviewer", "password": "correct-password"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "reviewer"
    assert response.cookies.get("ivida_review_session")


def test_reviewer_cannot_use_admin_dependency(client, reviewer_session) -> None:
    response = client.post("/api/admin/extraction-runs/run-1/retry")
    assert response.status_code == 403
```

- [ ] **Step 2: Run and verify failure**

```powershell
uv run pytest tests\test_auth_api.py -q
```

- [ ] **Step 3: Add Argon2 and database tables**

Add `argon2-cffi>=25,<26`. Create `admin_users` and hashed `admin_sessions`; store only SHA-256 session-token hashes. Sessions expire after eight hours.

- [ ] **Step 4: Implement role dependencies**

```python
class AdminRole(StrEnum):
    REVIEWER = "reviewer"
    ADMIN = "admin"


def require_reviewer(session=Depends(authenticate_session)) -> AuthenticatedUser:
    return session.user


def require_admin(user=Depends(require_reviewer)) -> AuthenticatedUser:
    if user.role != AdminRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
```

- [ ] **Step 5: Add CLI without default credentials**

`create_admin.py --username NAME --role reviewer|admin` must prompt for the password twice with `getpass`, reject passwords shorter than 12 characters and never print the password.

- [ ] **Step 6: Run tests and migration SQL**

```powershell
uv run alembic upgrade head --sql
uv run pytest tests\test_auth_api.py -q
uv run pytest -q
```

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml uv.lock app migrations/versions/20260729_05_add_admin_users_and_sessions.py tests/test_auth_api.py
git commit -m "feat: add reviewer authentication"
```

---

### Task 2: Persist immutable document versions and audit actions

**Files:**
- Create: `app/domain/document_versions.py`
- Modify: `app/infra/database_models.py`
- Create: `app/infra/postgres_review_repository.py`
- Create: `migrations/versions/20260729_06_add_document_versions_and_reviews.py`
- Test: `tests/test_postgres_review_repository.py`

**Interfaces:**
- Produces: `ReviewRepository.create_version()`, `append_action()`, `get_latest_version()`, `get_approved_version()`.
- Consumes: drafts from Phase A and authenticated user IDs.

- [ ] **Step 1: Write failing immutability tests**

```python
def test_approved_version_cannot_be_updated(repository, approved_version) -> None:
    with pytest.raises(ApprovedVersionImmutable):
        repository.update_version_json(
            approved_version.version_id,
            {"document_number": "CHANGED"},
        )


def test_review_action_records_old_and_new_values(repository, reviewer) -> None:
    action = repository.append_action(
        version_id=version_id,
        actor_user_id=reviewer.user_id,
        action="field_changed",
        field_path="items[0].quantity",
        old_value="8",
        new_value="7",
        reason="Counted seven cases",
    )
    assert action.old_value == "8"
```

- [ ] **Step 2: Run and verify failure**

```powershell
uv run pytest tests\test_postgres_review_repository.py -q
```

- [ ] **Step 3: Add version and action models**

Statuses:

```python
class DocumentVersionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
```

Create `document_versions` with version number unique per task, JSONB document, status, source draft ID, created-by user and timestamps. Create append-only `review_actions` with old/new JSON values and reason.

- [ ] **Step 4: Enforce immutability in repository and database**

All edits create a new draft version. Repository update methods must contain `WHERE status = 'draft'` and require exactly one affected row. Add a PostgreSQL trigger that rejects UPDATE and DELETE for approved versions and rejects UPDATE/DELETE for review actions.

- [ ] **Step 5: Run tests**

```powershell
uv run alembic upgrade head --sql
uv run pytest tests\test_postgres_review_repository.py -q
uv run pytest -q
```

- [ ] **Step 6: Commit**

```powershell
git add app/domain app/infra migrations/versions/20260729_06_add_document_versions_and_reviews.py tests/test_postgres_review_repository.py
git commit -m "feat: persist immutable review versions"
```

---

### Task 3: Implement ReviewService and review APIs

**Files:**
- Create: `app/services/review_service.py`
- Create: `app/api/review_routes.py`
- Create: `app/api/schemas/review.py`
- Modify: `app/main.py`
- Test: `tests/test_review_service.py`
- Test: `tests/test_review_api.py`

**Interfaces:**
- Produces: draft creation, patch, validate, approve and reject operations.
- Produces: `GET /api/review/tasks`, `GET /api/review/tasks/{task_id}`, `PATCH /api/review/versions/{version_id}`, `POST /api/review/versions/{version_id}/approve`, `POST /api/review/versions/{version_id}/reject`.

- [ ] **Step 1: Write failing approval-gate tests**

```python
def test_blocking_issue_prevents_approval(service, reviewer, version) -> None:
    with pytest.raises(UnresolvedBlockingIssues):
        service.approve(version.version_id, reviewer, reason="Checked")


def test_approval_creates_immutable_version(service, reviewer, valid_version) -> None:
    approved = service.approve(valid_version.version_id, reviewer, reason="Verified")
    assert approved.status == DocumentVersionStatus.APPROVED
    assert approved.approved_by == reviewer.user_id
```

- [ ] **Step 2: Run and verify failure**

```powershell
uv run pytest tests\test_review_service.py tests\test_review_api.py -q
```

- [ ] **Step 3: Implement service transactions**

`save_edit()`:

1. lock the latest draft
2. apply a typed JSON Patch limited to approved field paths
3. validate with `Invoice` or `ReceiveNote`
4. rerun deterministic validation
5. create a new draft version
6. append field-level audit actions
7. commit atomically

`approve()` requires zero unresolved blocking issues and creates an approved version in one transaction. `reject()` requires a non-empty reason.

- [ ] **Step 4: Implement APIs with authentication**

All review routes use `require_reviewer`. Retry and Provider configuration routes use `require_admin`. Return HTTP 409 for optimistic-version conflicts and unresolved blockers.

- [ ] **Step 5: Run tests**

```powershell
uv run pytest tests\test_review_service.py tests\test_review_api.py -q
uv run pytest -q
```

- [ ] **Step 6: Commit**

```powershell
git add app/services/review_service.py app/api/review_routes.py app/api/schemas/review.py app/main.py tests
git commit -m "feat: add human document review workflow"
```

---

### Task 4: Gate and persist reconciliation

**Files:**
- Create: `app/domain/reconciliation_records.py`
- Modify: `app/infra/database_models.py`
- Create: `app/infra/postgres_reconciliation_repository.py`
- Create: `app/services/reconciliation_application_service.py`
- Modify: `app/api/routes.py`
- Create: `migrations/versions/20260729_07_add_reconciliation_records.py`
- Test: `tests/test_reconciliation_gate.py`

**Interfaces:**
- Produces: `ReconciliationApplicationService.compare(approved_invoice_version_id, approved_receive_note_version_ids)`.
- Persists a result linked to immutable version IDs.
- `ReconciliationApplicationService` is the approval and persistence boundary around the existing deterministic `reconcile()` function.

- [ ] **Step 1: Write failing gate tests**

```python
def test_draft_invoice_is_rejected(service, draft_invoice, approved_note) -> None:
    with pytest.raises(DocumentNotApproved):
        service.compare(draft_invoice.version_id, [approved_note.version_id])


def test_approved_versions_create_persistent_result(
    service, approved_invoice, approved_notes
) -> None:
    record = service.compare(
        approved_invoice.version_id,
        [note.version_id for note in approved_notes],
    )
    assert record.invoice_version_id == approved_invoice.version_id
    assert record.result.summary.total_lines > 0
```

- [ ] **Step 2: Run and verify failure**

```powershell
uv run pytest tests\test_reconciliation_gate.py -q
```

- [ ] **Step 3: Add relational records**

Create `reconciliations`, `reconciliation_receive_notes` and `reconciliation_line_results`. Enforce unique result version and foreign keys to approved document versions.

- [ ] **Step 4: Implement gate and calculation**

Load versions with row locks, verify status is approved, validate JSON to `Invoice`/`ReceiveNote`, call existing deterministic `reconcile()`, and persist header/line results in one transaction.

- [ ] **Step 5: Replace public raw-JSON comparison endpoint**

Keep `/api/reconciliations/compare` only in development or tests. Add production endpoint:

```text
POST /api/reconciliations
{
  "invoice_version_id": "00000000-0000-0000-0000-000000000101",
  "receive_note_version_ids": ["00000000-0000-0000-0000-000000000201"]
}
```

Require an authenticated reviewer.

- [ ] **Step 6: Run tests and commit**

```powershell
uv run alembic upgrade head --sql
uv run pytest tests\test_reconciliation_gate.py -q
uv run pytest -q
git add app migrations/versions/20260729_07_add_reconciliation_records.py tests
git commit -m "feat: reconcile approved document versions"
```

---

### Task 5: Scaffold the review frontend

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/auth/LoginPage.tsx`
- Create: `frontend/src/review/ReviewQueuePage.tsx`
- Create: `frontend/src/review/ReviewDocumentPage.tsx`
- Create: `frontend/src/styles.css`
- Test: `frontend/src/auth/LoginPage.test.tsx`
- Test: `frontend/src/review/ReviewQueuePage.test.tsx`

**Interfaces:**
- Consumes: auth and review APIs from Tasks 1 and 3.
- Produces: browser UI on `http://localhost:5274`.

- [ ] **Step 1: Create Vite React TypeScript project configuration**

Use React, React Router, TanStack Query, Vitest, Testing Library and TypeScript. Configure proxy `/api -> http://127.0.0.1:8200`.

- [ ] **Step 2: Write failing login test**

```tsx
it("logs in and opens the review queue", async () => {
  render(<LoginPage />);
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText("Password"), "correct-password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByText("Review queue")).toBeVisible();
});
```

- [ ] **Step 3: Write failing queue test**

```tsx
it("shows blocking and warning counts", async () => {
  render(<ReviewQueuePage />);
  expect(await screen.findByText("SCF-INV-260701")).toBeVisible();
  expect(screen.getByText("1 blocking")).toBeVisible();
});
```

- [ ] **Step 4: Implement login and authenticated client**

Use secure HTTP-only cookie sessions. `fetch` always uses `credentials: "include"`. A 401 clears client state and redirects to `/login`.

- [ ] **Step 5: Implement queue and document page**

Queue filters: document type, status, blocking/warning, supplier and date. Document page:

- PDF viewer on the left
- editable header and lines on the right
- validation issue panel
- evidence text and page/block details
- Save draft, Approve and Reject actions

Approve is disabled while blockers exist.

- [ ] **Step 6: Run tests and build**

```powershell
cd frontend
npm install
npm test -- --run
npm run typecheck
npm run build
```

- [ ] **Step 7: Commit**

```powershell
git add frontend
git commit -m "feat: add document review frontend"
```

---

### Task 6: Add end-to-end acceptance and operating instructions

**Files:**
- Create: `tests/e2e/review_workflow.spec.ts`
- Create: `playwright.config.ts`
- Create: `run_review_frontend.ps1`
- Modify: `README.md`
- Create: `docs/operations/review-workflow.md`

**Interfaces:**
- Verifies upload -> extraction -> review -> approval -> reconciliation.

- [ ] **Step 1: Write the Playwright workflow**

The test:

1. logs in as a dedicated test reviewer
2. uploads case 01 Invoice and Receive Note
3. waits for both to become ready for review
4. opens evidence and validation panels
5. approves both documents
6. creates reconciliation
7. asserts three exact lines and `requires_review=false`

Use an evaluation fixture Provider for the default E2E run. Paid MinerU E2E remains a separate opt-in command.

- [ ] **Step 2: Run backend, worker and frontend in test mode**

```powershell
uv run python init_database.py
uv run python run_api.py
uv run python run_extraction_worker.py
cd frontend
npm run dev -- --host 127.0.0.1 --port 5274
```

- [ ] **Step 3: Run acceptance**

```powershell
npx playwright test tests/e2e/review_workflow.spec.ts
```

Expected: PASS with no unapproved reconciliation record.

- [ ] **Step 4: Document operations**

Document startup order, worker health, migration, retry semantics, password creation, token rotation, backup boundaries, MinIO paths, PostgreSQL tables and log redaction checks.

- [ ] **Step 5: Run final verification**

```powershell
uv run pytest -q
uv run python tools\validate_evaluation_dataset.py
cd frontend
npm test -- --run
npm run typecheck
npm run build
npx playwright test
```

- [ ] **Step 6: Commit**

```powershell
git add tests/e2e playwright.config.ts run_review_frontend.ps1 README.md docs/operations
git commit -m "test: verify reviewed reconciliation workflow"
```

## Phase B Completion Gate

Require:

- backend, frontend and E2E tests pass
- every reconciliation references approved version IDs
- approved versions and audit actions are immutable
- Reviewer cannot access Admin operations
- blockers prevent approval
- original and MinerU artifacts are never public
- `.env` is ignored and no token appears in Git
