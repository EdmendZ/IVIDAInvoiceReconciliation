# Reconciliation Case Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable exception-case workflow in which reviewers claim abnormal reconciliations, resolve every actionable difference, and submit them for administrator approval or voiding.

**Architecture:** Keep `ReconciliationRecord` as an immutable deterministic snapshot and add a separate `ReconciliationCase` aggregate for mutable human workflow state. A pure case factory and application service enforce the state machine; PostgreSQL repositories persist the current read model plus append-only actions, use optimistic revisions for concurrency, and atomically create an abnormal Reconciliation and its Case. A dedicated FastAPI router and two React pages expose the queue and detail workflows.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL/JSONB, pytest, React 19, TypeScript 5.8, TanStack Query, Vitest, Vite.

## Global Constraints

- Source of truth: `docs/superpowers/specs/2026-08-03-reconciliation-case-workflow-design.md`.
- Preserve the existing deterministic `ReconciliationResult`; human actions never rewrite its JSON or line results.
- `requires_review=false` creates no Case; `cleared` remains a derived presentation state.
- Reuse only `reviewer` and `admin`; do not add an `approver` role.
- Only the assigned Reviewer edits or submits a Case; other Reviewers have read-only access.
- `approved` and `voided` are immutable terminal states.
- Every mutation requires `expected_revision` and appends one `case_actions` row in the same transaction.
- No attachments, notifications, SLA reporting, automatic assignment, native `.xlsx`, or unrelated refactoring.
- Preserve the current uncommitted CSV export work. Before execution, commit it separately or move execution to a clean worktree; never discard or mix it into Case commits.
- Follow `docs/documentation-policy.md`; behavior changes and their documentation ship together.

---

## File Structure

### New backend files

- `app/domain/reconciliation_cases.py`: Case enums, models, list query/page contracts, and state-independent value validation.
- `app/services/reconciliation_case_factory.py`: Pure conversion from an abnormal Reconciliation into Case Items and the initial `created` Action.
- `app/services/reconciliation_case_service.py`: Role, assignment, state-transition, submission, and optimistic-revision rules.
- `app/infra/postgres_reconciliation_case_repository.py`: Case list/detail queries and atomic Case mutations.
- `app/api/reconciliation_case_routes.py`: HTTP request models, error mapping, and Case endpoints.
- `migrations/versions/20260803_11_add_reconciliation_cases.py`: Tables, indexes, constraints, and immutability triggers.
- `tests/test_reconciliation_case_factory.py`: Item-generation tests.
- `tests/test_reconciliation_case_service.py`: State and permission matrix.
- `tests/test_postgres_reconciliation_case_repository.py`: Persistence, action, ordering, and revision-conflict tests.
- `tests/test_reconciliation_case_api.py`: Auth, role, schema, filtering, and stable error-code tests.

### New frontend files

- `frontend/src/cases/caseTypes.ts`: API DTOs and enums.
- `frontend/src/cases/casePresentation.ts`: Pure permission, label, and submission-presentation rules.
- `frontend/src/cases/casePresentation.test.ts`: Pure frontend rule tests.
- `frontend/src/cases/CaseQueuePage.tsx`: Queue tabs, filters, pagination, claim action, and navigation.
- `frontend/src/cases/CaseDetailPage.tsx`: Immutable result, resolutions, audit history, Reviewer submission, and Admin decisions.

### Existing files to modify

- `app/domain/reconciliation_records.py`: Carry stable persisted line IDs without altering `ReconciliationResult`.
- `app/infra/database_models.py`: Add ORM rows.
- `app/infra/postgres_reconciliation_repository.py`: Atomically persist Reconciliation, line IDs, and optional initial Case.
- `app/services/reconciliation_application_service.py`: Generate stable line IDs and invoke the pure Case factory.
- `app/api/dependencies.py`: Wire repositories and service.
- `app/main.py`: Register the Case router.
- `tests/auth_helpers.py`: Add authenticated Admin client support.
- `tests/test_reconciliation_gate.py`: Verify clean vs abnormal atomic creation behavior.
- `tests/test_route_governance.py`: Verify Case routes require authentication.
- `frontend/src/api/client.ts`: Preserve structured Case error codes.
- `frontend/src/app/App.tsx`: Add Cases navigation and route parsing.
- `frontend/src/styles.css`: Add queue/detail/read-only/audit styles.
- `docs/business/06-reconciliation-rules.md`: Explain the Case boundary and state machine.
- `docs/architecture/07-data-and-infrastructure.md`: Explain new tables and transaction boundary.
- `docs/operations/08-api-ui-and-local-run.md`: Explain Case UI operations.
- `docs/operations/13-error-codes-and-troubleshooting.md`: Document stable Case errors.
- `docs/reference/11-api-contracts.md`: Document endpoints and payloads.
- `docs/reference/12-database-dictionary.md`: Document tables, keys, and triggers.
- `docs/reference/15-glossary.md`: Add Case, claim, resolution, and void terms.
- `docs/code-document-map.json`: Route Case source paths to synchronized documents.
- `README.md`: Add the Case workflow to the current-stage capability list.

---

### Task 1: Define the Case Domain Contract and Pure Factory

**Files:**
- Create: `app/domain/reconciliation_cases.py`
- Create: `app/services/reconciliation_case_factory.py`
- Create: `tests/test_reconciliation_case_factory.py`

**Interfaces:**
- Consumes: `ReconciliationRecord`, stable `line_result_ids: list[str]`, `created_by: str`, and `now: datetime`.
- Produces: `CaseStatus`, `CaseItemType`, `ResolutionType`, `CaseActionType`, `AssignmentFilter`, `ReconciliationCase`, `CaseItem`, `CaseAction`, `ReconciliationCaseBundle`, `CaseSummary`, `CaseActionView`, `CaseDetail`, `CaseListQuery`, `CasePage`, and `build_case_bundle(...) -> ReconciliationCaseBundle | None`.

- [ ] **Step 1: Write failing factory tests**

```python
def test_clean_reconciliation_does_not_create_case() -> None:
    record = reconciliation_record(requires_review=False, lines=[])
    assert build_case_bundle(record, [], now=NOW) is None


def test_abnormal_result_creates_line_and_header_items() -> None:
    record = reconciliation_record(
        requires_review=True,
        purchase_order_match=False,
        currency_match=False,
        lines=[line("mismatch"), line("exact"), line("within_tolerance")],
    )
    bundle = build_case_bundle(record, ["line-0", "line-1", "line-2"], now=NOW)
    assert bundle is not None
    assert bundle.case.status == CaseStatus.UNASSIGNED
    assert [item.item_type for item in bundle.items] == [
        CaseItemType.LINE,
        CaseItemType.PURCHASE_ORDER_CONFLICT,
        CaseItemType.CURRENCY_CONFLICT,
    ]
    assert bundle.items[0].line_result_id == "line-0"
    assert [action.action for action in bundle.actions] == [CaseActionType.CREATED]
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_reconciliation_case_factory.py -q`

Expected: FAIL because `app.domain.reconciliation_cases` and the factory do not exist.

- [ ] **Step 3: Add exact enums and Pydantic models**

```python
class CaseStatus(StrEnum):
    UNASSIGNED = "unassigned"
    IN_PROGRESS = "in_progress"
    PENDING_APPROVAL = "pending_approval"
    PENDING_VOID = "pending_void"
    APPROVED = "approved"
    VOIDED = "voided"


class CaseItemType(StrEnum):
    LINE = "line"
    PURCHASE_ORDER_CONFLICT = "purchase_order_conflict"
    CURRENCY_CONFLICT = "currency_conflict"


class ResolutionType(StrEnum):
    BUSINESS_EXCEPTION = "business_exception"
    DOCUMENT_DATA_ERROR = "document_data_error"
    MATCHING_ERROR = "matching_error"
    WAITING_FOR_DOCUMENTS = "waiting_for_documents"


class CaseActionType(StrEnum):
    CREATED = "created"
    CLAIMED = "claimed"
    REASSIGNED = "reassigned"
    RESOLUTION_CHANGED = "resolution_changed"
    SUBMITTED_FOR_APPROVAL = "submitted_for_approval"
    SUBMITTED_FOR_VOID = "submitted_for_void"
    RETURNED = "returned"
    APPROVED = "approved"
    VOIDED = "voided"
```

Define the aggregate and read models with these exact fields:

```python
class ReconciliationCase(BaseModel):
    case_id: str
    reconciliation_id: str
    status: CaseStatus
    assignee_user_id: str | None = None
    revision: int = Field(ge=1)
    created_by: str
    created_at: datetime
    claimed_at: datetime | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None

class CaseItem(BaseModel):
    item_id: str
    case_id: str
    item_type: CaseItemType
    line_result_id: str | None = None
    resolution_type: ResolutionType | None = None
    resolution_note: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    updated_at: datetime

class CaseAction(BaseModel):
    action_id: str
    case_id: str
    item_id: str | None = None
    actor_user_id: str
    action: CaseActionType
    old_value: object | None = None
    new_value: object | None = None
    reason: str | None = None
    created_at: datetime

class ReconciliationCaseBundle(BaseModel):
    case: ReconciliationCase
    items: list[CaseItem]
    actions: list[CaseAction]

class CaseSummary(BaseModel):
    case: ReconciliationCase
    invoice_number: str
    receive_note_numbers: list[str]
    actionable_count: int
    assignee_username: str | None = None

class CaseActionView(BaseModel):
    action: CaseAction
    actor_username: str

class CaseDetail(BaseModel):
    case: ReconciliationCase
    items: list[CaseItem]
    actions: list[CaseActionView]
    reconciliation: ReconciliationRecord

class CaseListQuery(BaseModel):
    statuses: tuple[CaseStatus, ...] = ()
    assignment: AssignmentFilter = AssignmentFilter.ALL
    invoice_number: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)

class CasePage(BaseModel):
    items: list[CaseSummary]
    page: int
    page_size: int
    total: int
```

Reject blank non-null `resolution_note` values with a Pydantic validator.

- [ ] **Step 4: Implement the pure factory**

```python
ACTIONABLE = {
    MatchStatus.MISMATCH,
    MatchStatus.INVOICE_ONLY,
    MatchStatus.RECEIVE_NOTE_ONLY,
}


def build_case_bundle(
    record: ReconciliationRecord,
    line_result_ids: list[str],
    *,
    now: datetime,
) -> ReconciliationCaseBundle | None:
    if len(line_result_ids) != len(record.result.lines):
        raise ValueError("One line_result_id is required for every result line")
    if not record.result.summary.requires_review:
        return None
    case_id = str(uuid4())
    items = [
        CaseItem(
            item_id=str(uuid4()),
            case_id=case_id,
            item_type=CaseItemType.LINE,
            line_result_id=line_result_ids[index],
            updated_at=now,
        )
        for index, line in enumerate(record.result.lines)
        if line.status in ACTIONABLE
    ]
    if record.result.purchase_order_match is False:
        items.append(header_item(case_id, CaseItemType.PURCHASE_ORDER_CONFLICT, now))
    if record.result.currency_match is False:
        items.append(header_item(case_id, CaseItemType.CURRENCY_CONFLICT, now))
    if not items:
        raise ValueError("A review-required reconciliation must create a case item")
    case = ReconciliationCase(
        case_id=case_id,
        reconciliation_id=record.reconciliation_id,
        status=CaseStatus.UNASSIGNED,
        assignee_user_id=None,
        revision=1,
        created_by=record.created_by,
        created_at=now,
    )
    action = created_action(case_id, record.created_by, now)
    return ReconciliationCaseBundle(case=case, items=items, actions=[action])
```

- [ ] **Step 5: Run the focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_reconciliation_case_factory.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the domain unit**

```powershell
git add app/domain/reconciliation_cases.py app/services/reconciliation_case_factory.py tests/test_reconciliation_case_factory.py
git commit -m "feat: define reconciliation case domain"
```

---

### Task 2: Implement the Case State Machine with a Fake Repository

**Files:**
- Create: `app/services/reconciliation_case_service.py`
- Create: `tests/test_reconciliation_case_service.py`

**Interfaces:**
- Consumes: Task 1 domain models; `AuthenticatedUser`; a `ReconciliationCaseRepository` Protocol; and an `ActiveReviewerReader` Protocol.
- Produces: `CaseError(code, message)`, `ReconciliationCaseService.claim`, `reassign`, `set_resolution`, `submit_approval`, `submit_void`, `approve`, `return_case`, `void`, `get_detail`, and `list_cases`.

- [ ] **Step 1: Write the permission and transition matrix tests**

```python
def test_only_assignee_can_change_resolution() -> None:
    service, repository = service_with_claimed_case(assignee_id="reviewer-a")
    with pytest.raises(CaseError, match="CASE_ASSIGNEE_REQUIRED"):
        service.set_resolution(
            CASE_ID,
            ITEM_ID,
            ResolutionType.BUSINESS_EXCEPTION,
            "Approved short delivery",
            user=reviewer("reviewer-b"),
            expected_revision=2,
        )


def test_business_exceptions_submit_for_approval() -> None:
    service, repository = service_with_all_items(
        ResolutionType.BUSINESS_EXCEPTION,
        assignee_id="reviewer-a",
    )
    bundle = service.submit_approval(
        CASE_ID,
        user=reviewer("reviewer-a"),
        expected_revision=4,
    )
    assert bundle.case.status == CaseStatus.PENDING_APPROVAL
    assert repository.actions[-1].action == CaseActionType.SUBMITTED_FOR_APPROVAL


@pytest.mark.parametrize(
    "resolution",
    [ResolutionType.DOCUMENT_DATA_ERROR, ResolutionType.MATCHING_ERROR],
)
def test_data_or_matching_error_can_only_submit_void(resolution) -> None:
    service, _ = service_with_all_items(resolution, assignee_id="reviewer-a")
    with pytest.raises(CaseError, match="CASE_SUBMISSION_CONFLICT"):
        service.submit_approval(CASE_ID, user=reviewer("reviewer-a"), expected_revision=4)
    assert service.submit_void(
        CASE_ID, user=reviewer("reviewer-a"), expected_revision=4
    ).case.status == CaseStatus.PENDING_VOID
```

Add this table-driven guard coverage in the same test file:

```python
@pytest.mark.parametrize(
    ("operation", "status", "actor_role", "expected_code"),
    [
        ("approve", CaseStatus.IN_PROGRESS, AdminRole.ADMIN, "CASE_INVALID_TRANSITION"),
        ("approve", CaseStatus.PENDING_APPROVAL, AdminRole.REVIEWER, "CASE_ADMIN_REQUIRED"),
        ("void", CaseStatus.PENDING_VOID, AdminRole.REVIEWER, "CASE_ADMIN_REQUIRED"),
        ("claim", CaseStatus.IN_PROGRESS, AdminRole.REVIEWER, "CASE_ALREADY_CLAIMED"),
        ("set_resolution", CaseStatus.APPROVED, AdminRole.REVIEWER, "CASE_TERMINAL"),
        ("return_case", CaseStatus.VOIDED, AdminRole.ADMIN, "CASE_TERMINAL"),
    ],
)
def test_transition_guards(operation, status, actor_role, expected_code):
    service = service_for(status=status, actor_role=actor_role)
    with pytest.raises(CaseError) as captured:
        invoke(operation, service)
    assert captured.value.code == expected_code

def test_waiting_and_unresolved_items_cannot_submit() -> None:
    assert_submit_error(None, "CASE_ITEMS_INCOMPLETE")
    assert_submit_error(ResolutionType.WAITING_FOR_DOCUMENTS, "CASE_ITEMS_INCOMPLETE")

def test_return_and_reassign_require_reason_and_return_keeps_assignee() -> None:
    service = pending_service(assignee_id="reviewer-a")
    with pytest.raises(ValueError, match="reason"):
        service.return_case(CASE_ID, user=admin(), reason=" ", expected_revision=4)
    returned = service.return_case(
        CASE_ID, user=admin(), reason="Clarify supplier approval", expected_revision=4
    )
    assert returned.case.assignee_user_id == "reviewer-a"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_reconciliation_case_service.py -q`

Expected: FAIL because the service and repository Protocol do not exist.

- [ ] **Step 3: Define stable business errors and repository port**

```python
class CaseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ReconciliationCaseRepository(Protocol):
    def get_bundle(self, case_id: str) -> ReconciliationCaseBundle | None: ...
    def list_cases(self, query: CaseListQuery, user_id: str) -> CasePage: ...
    def save_case_mutation(
        self,
        bundle: ReconciliationCaseBundle,
        action: CaseAction,
        *,
        expected_revision: int,
    ) -> ReconciliationCaseBundle: ...


class ActiveReviewerReader(Protocol):
    def is_active_reviewer(self, user_id: str) -> bool: ...
```

`save_case_mutation` must be the single application-port operation for Case and Item changes so the concrete repository can update the read model, increment revision, and append the action atomically.

- [ ] **Step 4: Implement common guards**

```python
TERMINAL = {CaseStatus.APPROVED, CaseStatus.VOIDED}

def _require_revision(case: ReconciliationCase, expected: int) -> None:
    if case.revision != expected:
        raise CaseError("CASE_REVISION_CONFLICT", "Case has changed; refresh and retry")

def _require_assignee(case: ReconciliationCase, user: AuthenticatedUser) -> None:
    if case.assignee_user_id != user.user_id:
        raise CaseError("CASE_ASSIGNEE_REQUIRED", "Only the assignee can edit this case")

def _require_admin(user: AuthenticatedUser) -> None:
    if user.role != AdminRole.ADMIN:
        raise CaseError("CASE_ADMIN_REQUIRED", "Admin role required")
```

Each public method loads one bundle, checks terminal state before other mutations, checks revision, enforces role/state/assignee rules, creates exactly one Action, and calls `save_case_mutation` once.

`reassign` also calls `ActiveReviewerReader.is_active_reviewer(target_user_id)` and raises `CASE_INVALID_ASSIGNEE` unless the target exists, is active, and has role `reviewer`.

- [ ] **Step 5: Implement submission predicates exactly**

```python
def _submission_target(items: list[CaseItem]) -> CaseStatus:
    if any(item.resolution_type is None for item in items):
        raise CaseError("CASE_ITEMS_INCOMPLETE", "Every case item requires a resolution")
    if any(item.resolution_type == ResolutionType.WAITING_FOR_DOCUMENTS for item in items):
        raise CaseError("CASE_ITEMS_INCOMPLETE", "Documents are still outstanding")
    kinds = {item.resolution_type for item in items}
    if kinds == {ResolutionType.BUSINESS_EXCEPTION}:
        return CaseStatus.PENDING_APPROVAL
    if kinds & {ResolutionType.DOCUMENT_DATA_ERROR, ResolutionType.MATCHING_ERROR}:
        return CaseStatus.PENDING_VOID
    raise CaseError("CASE_SUBMISSION_CONFLICT", "Resolution combination cannot be submitted")
```

`submit_approval` accepts only `PENDING_APPROVAL`; `submit_void` accepts only `PENDING_VOID`. Admin approval and void repeat the predicate against current items so an API caller cannot bypass the service.

- [ ] **Step 6: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_reconciliation_case_service.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the state machine**

```powershell
git add app/services/reconciliation_case_service.py tests/test_reconciliation_case_service.py
git commit -m "feat: enforce reconciliation case workflow"
```

---

### Task 3: Add PostgreSQL Schema, Constraints, and Immutability Triggers

**Files:**
- Create: `migrations/versions/20260803_11_add_reconciliation_cases.py`
- Modify: `app/infra/database_models.py`
- Modify: `docs/reference/12-database-dictionary.md`
- Test: `tests/test_postgres_reconciliation_case_repository.py`

**Interfaces:**
- Consumes: Task 1 field names and enum string values.
- Produces: `ReconciliationCaseRow`, `CaseItemRow`, and `CaseActionRow` mapped to the three new tables.

- [ ] **Step 1: Write an ORM schema test**

```python
def test_case_schema_has_unique_reconciliation_and_revision() -> None:
    assert ReconciliationCaseRow.__table__.c.reconciliation_id.unique is True
    assert ReconciliationCaseRow.__table__.c.revision.nullable is False
    assert CaseActionRow.__table__.c.old_value.nullable is True
    assert CaseActionRow.__table__.c.new_value.nullable is True
```

- [ ] **Step 2: Run it and verify the missing-row failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_postgres_reconciliation_case_repository.py::test_case_schema_has_unique_reconciliation_and_revision -q`

Expected: FAIL because the ORM rows do not exist.

- [ ] **Step 3: Add ORM rows with exact keys and indexes**

Define:

```python
class ReconciliationCaseRow(Base):
    __tablename__ = "reconciliation_cases"
    case_id = mapped_column(String(36), primary_key=True)
    reconciliation_id = mapped_column(
        String(36), ForeignKey("reconciliations.reconciliation_id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    status = mapped_column(String(32), nullable=False)
    assignee_user_id = mapped_column(
        String(36), ForeignKey("admin_users.user_id", ondelete="RESTRICT"), nullable=True
    )
    revision = mapped_column(Integer, nullable=False)
```

Complete the rows with these columns:

```python
# ReconciliationCaseRow
created_by = mapped_column(
    String(36), ForeignKey("admin_users.user_id", ondelete="RESTRICT"), nullable=False
)
created_at = mapped_column(DateTime(timezone=True), nullable=False)
claimed_at = mapped_column(DateTime(timezone=True), nullable=True)
submitted_at = mapped_column(DateTime(timezone=True), nullable=True)
completed_at = mapped_column(DateTime(timezone=True), nullable=True)

# CaseItemRow
item_id = mapped_column(String(36), primary_key=True)
case_id = mapped_column(
    String(36), ForeignKey("reconciliation_cases.case_id", ondelete="CASCADE"), nullable=False
)
item_type = mapped_column(String(32), nullable=False)
line_result_id = mapped_column(
    String(36), ForeignKey("reconciliation_line_results.line_result_id", ondelete="RESTRICT"), nullable=True
)
resolution_type = mapped_column(String(32), nullable=True)
resolution_note = mapped_column(Text, nullable=True)
resolved_by = mapped_column(
    String(36), ForeignKey("admin_users.user_id", ondelete="RESTRICT"), nullable=True
)
resolved_at = mapped_column(DateTime(timezone=True), nullable=True)
updated_at = mapped_column(DateTime(timezone=True), nullable=False)

# CaseActionRow
action_id = mapped_column(String(36), primary_key=True)
case_id = mapped_column(
    String(36), ForeignKey("reconciliation_cases.case_id", ondelete="CASCADE"), nullable=False
)
item_id = mapped_column(
    String(36), ForeignKey("case_items.item_id", ondelete="RESTRICT"), nullable=True
)
actor_user_id = mapped_column(
    String(36), ForeignKey("admin_users.user_id", ondelete="RESTRICT"), nullable=False
)
action = mapped_column(String(64), nullable=False)
old_value = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
new_value = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
reason = mapped_column(Text, nullable=True)
created_at = mapped_column(DateTime(timezone=True), nullable=False)
```

Add indexes on Case status, assignee, `(created_at, case_id)`, Item case ID, and Action `(case_id, created_at, action_id)`.

Implement Item uniqueness with two partial unique indexes, not a single `(case_id, item_type)` constraint that would incorrectly allow only one line item:

```python
Index(
    "uq_case_items_line_result",
    "case_id",
    "line_result_id",
    unique=True,
    postgresql_where=text("line_result_id IS NOT NULL"),
    sqlite_where=text("line_result_id IS NOT NULL"),
),
Index(
    "uq_case_items_header_type",
    "case_id",
    "item_type",
    unique=True,
    postgresql_where=text("item_type <> 'line'"),
    sqlite_where=text("item_type <> 'line'"),
),
```

Add a check constraint requiring `line_result_id IS NOT NULL` exactly when `item_type='line'`, and a resolution constraint requiring a non-blank note, `resolved_by`, and `resolved_at` whenever `resolution_type` is non-null.

- [ ] **Step 4: Add Alembic revision `20260803_11`**

Set `down_revision = "20260731_10"`. Create the three tables in parent-to-child order. Add PostgreSQL check constraints for allowed status, item type, resolution type, and action strings. Add triggers that reject UPDATE/DELETE on `case_actions`, reject UPDATE/DELETE on a Case whose old status is `approved` or `voided`, and reject UPDATE/DELETE on `case_items` when the parent Case is terminal.

- [ ] **Step 5: Document the tables and downgrade order**

Update the database dictionary with every field, relationship, unique constraint, index, and trigger. Ensure `downgrade()` drops triggers/functions, then actions, items, and cases.

- [ ] **Step 6: Run schema and migration smoke checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_postgres_reconciliation_case_repository.py::test_case_schema_has_unique_reconciliation_and_revision -q
.\.venv\Scripts\python.exe -m alembic heads
```

Expected: test PASS and exactly one head, `20260803_11`.

- [ ] **Step 7: Commit schema and dictionary**

```powershell
git add app/infra/database_models.py migrations/versions/20260803_11_add_reconciliation_cases.py tests/test_postgres_reconciliation_case_repository.py docs/reference/12-database-dictionary.md
git commit -m "feat: add reconciliation case schema"
```

---

### Task 4: Persist Cases and Atomically Create Them with Reconciliations

**Files:**
- Modify: `app/domain/reconciliation_records.py`
- Modify: `app/infra/postgres_reconciliation_repository.py`
- Create: `app/infra/postgres_reconciliation_case_repository.py`
- Modify: `app/services/reconciliation_application_service.py`
- Modify: `tests/test_reconciliation_gate.py`
- Modify: `tests/test_postgres_reconciliation_repository.py`
- Modify: `tests/test_postgres_reconciliation_case_repository.py`

**Interfaces:**
- Consumes: `build_case_bundle`, Task 1 models, and Task 2 repository Protocol.
- Produces: `ReconciliationPersistenceBundle(record, line_result_ids, case)` and a PostgreSQL Case repository implementing Task 2's exact Protocol.

- [ ] **Step 1: Write failing atomic-creation tests**

```python
def test_abnormal_compare_persists_reconciliation_and_case_atomically() -> None:
    record = service.compare(INVOICE_VERSION, [NOTE_VERSION], created_by=REVIEWER_ID)
    stored = reconciliation_repository.get(record.reconciliation_id)
    case = case_repository.get_by_reconciliation(record.reconciliation_id)
    assert stored == record
    assert case is not None
    assert case.case.status == CaseStatus.UNASSIGNED


def test_clean_compare_persists_no_case() -> None:
    record = exact_match_service.compare(INVOICE_VERSION, [NOTE_VERSION], created_by=REVIEWER_ID)
    assert case_repository.get_by_reconciliation(record.reconciliation_id) is None
```

Add a transaction test that forces Case Item insertion to fail and asserts that no `reconciliations` row remains.

- [ ] **Step 2: Run the tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_reconciliation_gate.py tests\test_postgres_reconciliation_repository.py tests\test_postgres_reconciliation_case_repository.py -q`

Expected: FAIL because Reconciliation creation does not accept Case data and the Case repository is missing.

- [ ] **Step 3: Generate stable line IDs before persistence**

Add `line_result_ids: list[str]` to a new application-only `ReconciliationPersistenceBundle` model; do not add IDs inside `ReconciliationResult`. In `compare`:

```python
reconciliation_id = str(uuid4())
record = ReconciliationRecord(
    reconciliation_id=reconciliation_id,
    invoice_version_id=invoice_version.version_id,
    receive_note_version_ids=[version.version_id for version in note_versions],
    result=result,
    created_by=created_by,
    created_at=now,
)
line_result_ids = [str(uuid4()) for _ in result.lines]
case = build_case_bundle(record, line_result_ids, now=now)
return self._reconciliations.create(
    ReconciliationPersistenceBundle(
        record=record,
        line_result_ids=line_result_ids,
        case=case,
    )
)
```

- [ ] **Step 4: Make Reconciliation creation one PostgreSQL transaction**

Change `PostgresReconciliationRepository.create(bundle)` to use one Session for:

1. `ReconciliationRow`;
2. Receive Note links;
3. line rows zipped with `bundle.line_result_ids`;
4. optional `ReconciliationCaseRow`;
5. all initial `CaseItemRow` and the `created` `CaseActionRow`;
6. one final `session.commit()`.

Never call another repository method that opens a second Session from inside this transaction.

- [ ] **Step 5: Implement Case reads and conditional saves**

`PostgresReconciliationCaseRepository.get_bundle` returns current Case, Items, and Actions in `(created_at, action_id)` order. `save_case_mutation` performs:

```python
updated = session.execute(
    update(ReconciliationCaseRow)
    .where(
        ReconciliationCaseRow.case_id == bundle.case.case_id,
        ReconciliationCaseRow.revision == expected_revision,
    )
    .values(
        status=bundle.case.status.value,
        assignee_user_id=bundle.case.assignee_user_id,
        revision=expected_revision + 1,
        claimed_at=bundle.case.claimed_at,
        submitted_at=bundle.case.submitted_at,
        completed_at=bundle.case.completed_at,
    )
)
if updated.rowcount != 1:
    raise CaseError("CASE_REVISION_CONFLICT", "Case has changed; refresh and retry")
```

Then update the changed Item when `action.item_id` is present, insert exactly one Action, and commit once.

- [ ] **Step 6: Implement deterministic list/detail query ordering**

`list_cases` accepts `CaseListQuery(statuses, assignment, invoice_number, page, page_size)`, filters `mine` by the authenticated user ID, joins `reconciliations.result_json` for document numbers and `admin_users` for assignee display names, and orders by `(created_at ASC, case_id ASC)`. `get_detail` also joins Action actor usernames. Return `CasePage(items, page, page_size, total)`.

- [ ] **Step 7: Run repository and gate tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_reconciliation_gate.py tests\test_postgres_reconciliation_repository.py tests\test_postgres_reconciliation_case_repository.py -q`

Expected: PASS, including rollback and stale-revision cases.

- [ ] **Step 8: Commit persistence and atomic creation**

```powershell
git add app/domain/reconciliation_records.py app/services/reconciliation_application_service.py app/infra/postgres_reconciliation_repository.py app/infra/postgres_reconciliation_case_repository.py tests/test_reconciliation_gate.py tests/test_postgres_reconciliation_repository.py tests/test_postgres_reconciliation_case_repository.py
git commit -m "feat: persist reconciliation cases atomically"
```

---

### Task 5: Expose Authenticated Case APIs and Stable Errors

**Files:**
- Create: `app/api/reconciliation_case_routes.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/infra/postgres_admin_repository.py`
- Modify: `app/main.py`
- Modify: `tests/auth_helpers.py`
- Create: `tests/test_reconciliation_case_api.py`
- Modify: `tests/test_route_governance.py`
- Modify: `docs/reference/11-api-contracts.md`
- Modify: `docs/operations/13-error-codes-and-troubleshooting.md`

**Interfaces:**
- Consumes: Task 2 service and Task 4 repository.
- Produces: the ten workflow endpoints in the approved spec, one supporting assignee-list endpoint, and error bodies shaped as `{"detail": {"code": str, "message": str}}`. List returns `CasePage`; detail and every successful mutation return `CaseDetail`; assignees returns the safe user list.

- [ ] **Step 1: Add Reviewer/Admin test clients**

```python
TEST_ADMIN = AuthenticatedUser(
    user_id="00000000-0000-0000-0000-000000000098",
    username="test-admin",
    role=AdminRole.ADMIN,
)

@contextmanager
def admin_client(app: FastAPI) -> Iterator[TestClient]:
    previous = app.dependency_overrides.get(require_reviewer)
    app.dependency_overrides[require_reviewer] = lambda: TEST_ADMIN
    try:
        yield TestClient(app)
    finally:
        restore_override(app, require_reviewer, previous)
```

Refactor the existing Reviewer context manager to use the same `restore_override` helper.

- [ ] **Step 2: Write failing API contract tests**

```python
def test_reviewer_claims_and_updates_resolution() -> None:
    with reviewer_client(app) as client:
        claimed = client.post(f"/api/reconciliation-cases/{CASE_ID}/claim", json={"expected_revision": 1})
        assert claimed.status_code == 200
        assert claimed.json()["case"]["status"] == "in_progress"
        updated = client.put(
            f"/api/reconciliation-cases/{CASE_ID}/items/{ITEM_ID}/resolution",
            json={
                "resolution_type": "business_exception",
                "note": "Supplier approved short delivery",
                "expected_revision": 2,
            },
        )
        assert updated.json()["revision"] == 3


def test_reviewer_cannot_approve() -> None:
    with reviewer_client(app) as client:
        response = client.post(
            f"/api/reconciliation-cases/{CASE_ID}/approve",
            json={"expected_revision": 4},
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CASE_ADMIN_REQUIRED"
```

Add tests for every endpoint, repeated `status` filters/page bounds, 404, all stable 403/409 codes, mandatory reasons, inactive/non-Reviewer assignees, and unauthenticated route governance.

```python
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/reconciliation-cases"),
        ("get", f"/api/reconciliation-cases/{CASE_ID}"),
        ("post", f"/api/reconciliation-cases/{CASE_ID}/claim"),
        ("post", f"/api/reconciliation-cases/{CASE_ID}/reassign"),
        ("put", f"/api/reconciliation-cases/{CASE_ID}/items/{ITEM_ID}/resolution"),
        ("post", f"/api/reconciliation-cases/{CASE_ID}/submit-approval"),
        ("post", f"/api/reconciliation-cases/{CASE_ID}/submit-void"),
        ("post", f"/api/reconciliation-cases/{CASE_ID}/approve"),
        ("post", f"/api/reconciliation-cases/{CASE_ID}/return"),
        ("post", f"/api/reconciliation-cases/{CASE_ID}/void"),
    ],
)
def test_case_routes_require_authentication(method, path) -> None:
    response = getattr(TestClient(app), method)(path, json={"expected_revision": 1})
    assert response.status_code == 401

def test_assignee_list_is_admin_only_and_safe() -> None:
    with reviewer_client(app) as client:
        assert client.get("/api/reconciliation-cases/assignees").status_code == 403
    with admin_client(app) as client:
        response = client.get("/api/reconciliation-cases/assignees")
    assert response.json() == [{"user_id": REVIEWER_ID, "username": "reviewer-a"}]
    assert "password_hash" not in response.text

@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("CASE_NOT_FOUND", 404),
        ("CASE_ASSIGNEE_REQUIRED", 403),
        ("CASE_ADMIN_REQUIRED", 403),
        ("CASE_REVISION_CONFLICT", 409),
        ("CASE_INVALID_TRANSITION", 409),
        ("CASE_ITEMS_INCOMPLETE", 409),
        ("CASE_SUBMISSION_CONFLICT", 409),
        ("CASE_TERMINAL", 409),
        ("CASE_INVALID_ASSIGNEE", 409),
    ],
)
def test_case_errors_have_stable_code_and_status(code, status) -> None:
    service = ErroringCaseService(CaseError(code, "test message"))
    response = call_route_with_overridden_service(service, code)
    assert response.status_code == status
    assert response.json()["detail"] == {"code": code, "message": "test message"}
```

Add `GET /api/reconciliation-cases/assignees` for Admin users. It returns active users whose role is `reviewer` as `[{"user_id": str, "username": str}]`; this supports the reassign control and does not expose password hashes or sessions. Extend `PostgresAdminRepository` with:

```python
def list_active_reviewers(self) -> list[AuthenticatedUser]:
    with self._session_factory() as session:
        rows = session.scalars(
            select(AdminUserRow)
            .where(
                AdminUserRow.role == AdminRole.REVIEWER.value,
                AdminUserRow.is_active.is_(True),
            )
            .order_by(AdminUserRow.username, AdminUserRow.user_id)
        ).all()
        return [
            AuthenticatedUser(user_id=row.user_id, username=row.username, role=row.role)
            for row in rows
        ]

def is_active_reviewer(self, user_id: str) -> bool:
    with self._session_factory() as session:
        return session.scalar(
            select(AdminUserRow.user_id).where(
                AdminUserRow.user_id == user_id,
                AdminUserRow.role == AdminRole.REVIEWER.value,
                AdminUserRow.is_active.is_(True),
            )
        ) is not None
```

- [ ] **Step 3: Wire the repository and service**

```python
@lru_cache
def get_reconciliation_case_repository() -> PostgresReconciliationCaseRepository:
    return PostgresReconciliationCaseRepository(get_session_factory())

@lru_cache
def get_admin_repository() -> PostgresAdminRepository:
    return PostgresAdminRepository(get_session_factory())

@lru_cache
def get_reconciliation_case_service() -> ReconciliationCaseService:
    return ReconciliationCaseService(
        get_reconciliation_case_repository(),
        active_reviewer_reader=get_admin_repository(),
    )
```

- [ ] **Step 4: Implement request models and error mapping**

Define exact request models:

```python
class RevisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)

class ResolutionRequest(RevisionRequest):
    resolution_type: ResolutionType
    note: str = Field(min_length=1)

class ReassignRequest(RevisionRequest):
    assignee_user_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)

class ReturnRequest(RevisionRequest):
    reason: str = Field(min_length=1)
```

Map `CaseError` codes to 403 only for `CASE_ASSIGNEE_REQUIRED` and `CASE_ADMIN_REQUIRED`, to 404 for `CASE_NOT_FOUND`, and to 409 for all state/revision conflicts.

```python
def case_http_error(error: CaseError) -> HTTPException:
    status_code = 404 if error.code == "CASE_NOT_FOUND" else (
        403 if error.code in {"CASE_ASSIGNEE_REQUIRED", "CASE_ADMIN_REQUIRED"} else 409
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )
```

- [ ] **Step 5: Register routes and enforce authentication**

Use `require_reviewer` on all route functions. Pass the authenticated user into the service; do not trust a user ID from request JSON. Register the router in `app/main.py`.

For each successful mutation, call the service mutation once and then return `service.get_detail(case_id)` so every frontend mutation receives the same `CaseDetail` shape.

Declare static `GET /api/reconciliation-cases/assignees` before `/{case_id}` routes so `assignees` is never parsed as a Case ID. Require `admin` inside the endpoint before calling `get_admin_repository().list_active_reviewers()`. Accept repeated query parameters such as `?status=pending_approval&status=pending_void`; convert them to `CaseListQuery.statuses`.

- [ ] **Step 6: Update API and troubleshooting documentation**

Document exact payloads, response fields, pagination, role requirements, status transitions, and each stable Case error code.

- [ ] **Step 7: Run API tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_reconciliation_case_api.py tests\test_route_governance.py -q`

Expected: PASS.

- [ ] **Step 8: Commit the API slice**

```powershell
git add app/api/reconciliation_case_routes.py app/api/dependencies.py app/infra/postgres_admin_repository.py app/main.py tests/auth_helpers.py tests/test_reconciliation_case_api.py tests/test_route_governance.py docs/reference/11-api-contracts.md docs/operations/13-error-codes-and-troubleshooting.md
git commit -m "feat: expose reconciliation case APIs"
```

---

### Task 6: Add Frontend Case Types, Structured Errors, and Presentation Rules

**Files:**
- Create: `frontend/src/cases/caseTypes.ts`
- Create: `frontend/src/cases/casePresentation.ts`
- Create: `frontend/src/cases/casePresentation.test.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Consumes: Task 5 JSON contracts.
- Produces: `CaseSummary`, `CaseDetail`, `CaseItem`, `CaseAction`, `CasePage`, `ApiError`, `canEditCase`, `availableSubmission`, and label helpers.

- [ ] **Step 1: Write failing pure presentation tests**

```typescript
it("allows only the assigned reviewer to edit", () => {
  expect(canEditCase(claimedCase("reviewer-a"), reviewer("reviewer-a"))).toBe(true);
  expect(canEditCase(claimedCase("reviewer-a"), reviewer("reviewer-b"))).toBe(false);
  expect(canEditCase(claimedCase("reviewer-a"), admin())).toBe(false);
});

it("derives approval and void submissions from resolutions", () => {
  expect(availableSubmission([item("business_exception")])).toBe("approval");
  expect(availableSubmission([item("document_data_error")])).toBe("void");
  expect(availableSubmission([item("waiting_for_documents")])).toBe(null);
  expect(availableSubmission([item(null)])).toBe(null);
});
```

- [ ] **Step 2: Run tests and verify missing-module failure**

Run from `frontend`: `npm test -- --run src/cases/casePresentation.test.ts`

Expected: FAIL because the types and presentation module do not exist.

- [ ] **Step 3: Add DTOs matching the API exactly**

```typescript
export type CaseStatus =
  | "unassigned" | "in_progress" | "pending_approval"
  | "pending_void" | "approved" | "voided";
export type ResolutionType =
  | "business_exception" | "document_data_error"
  | "matching_error" | "waiting_for_documents";
export type CaseItemType =
  | "line" | "purchase_order_conflict" | "currency_conflict";

export type ReconciliationCase = {
  case_id: string;
  reconciliation_id: string;
  status: CaseStatus;
  assignee_user_id: string | null;
  revision: number;
  created_by: string;
  created_at: string;
  claimed_at: string | null;
  submitted_at: string | null;
  completed_at: string | null;
};
export type CaseItem = {
  item_id: string;
  case_id: string;
  item_type: CaseItemType;
  line_result_id: string | null;
  resolution_type: ResolutionType | null;
  resolution_note: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  updated_at: string;
};
export type CaseDetail = {
  case: ReconciliationCase;
  items: CaseItem[];
  actions: CaseActionView[];
  reconciliation: ReconciliationRecord;
};
export type CasePage = {
  items: CaseSummary[];
  page: number;
  page_size: number;
  total: number;
};
```

```typescript
export type CaseSummary = {
  case: ReconciliationCase;
  invoice_number: string;
  receive_note_numbers: string[];
  actionable_count: number;
  assignee_username: string | null;
};
export type CaseActionView = {
  action: {
    action_id: string;
    case_id: string;
    item_id: string | null;
    actor_user_id: string;
    action: string;
    old_value: unknown;
    new_value: unknown;
    reason: string | null;
    created_at: string;
  };
  actor_username: string;
};
export type ReconciliationRecord = {
  reconciliation_id: string;
  invoice_version_id: string;
  receive_note_version_ids: string[];
  created_by: string;
  created_at: string;
  result: {
    invoice_number: string;
    receive_note_numbers: string[];
    purchase_order_match: boolean | null;
    currency_match: boolean;
    summary: {
      total_lines: number;
      exact_lines: number;
      tolerance_lines: number;
      mismatch_lines: number;
      invoice_only_lines: number;
      receive_note_only_lines: number;
      requires_review: boolean;
    };
    lines: Array<{
      match_key: string;
      sku: string | null;
      description: string;
      invoice_quantity: string;
      received_quantity: string;
      quantity_difference: string;
      invoice_unit_price: string | null;
      received_unit_price: string | null;
      unit_price_difference: string | null;
      invoice_amount: string | null;
      received_amount: string | null;
      amount_difference: string | null;
      status: string;
      reasons: string[];
    }>;
  };
};
```

- [ ] **Step 4: Preserve structured API errors**

```typescript
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

const detail = body.detail;
const message = typeof detail === "string"
  ? detail
  : detail?.message ?? `Request failed (${response.status})`;
const code = typeof detail === "object" ? detail?.code : undefined;
throw new ApiError(message, response.status, code);
```

Apply this parsing in the shared JSON request path without changing upload/download success behavior.

- [ ] **Step 5: Implement and test presentation rules**

Keep permission/submission derivation pure. Use explicit switch statements for status and resolution labels so unknown backend values fail TypeScript exhaustiveness checks.

Run from `frontend`: `npm test -- --run src/cases/casePresentation.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit frontend contracts**

```powershell
git add frontend/src/cases/caseTypes.ts frontend/src/cases/casePresentation.ts frontend/src/cases/casePresentation.test.ts frontend/src/api/client.ts
git commit -m "feat: add reconciliation case frontend contracts"
```

---

### Task 7: Build the Case Queue and Claim Workflow

**Files:**
- Create: `frontend/src/cases/CaseQueuePage.tsx`
- Create: `frontend/src/cases/CaseDetailPage.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `docs/operations/08-api-ui-and-local-run.md`

**Interfaces:**
- Consumes: `CasePage`, `CaseDetail`, `ApiError`, `api`, and the existing `onNavigate(path)` convention.
- Produces: `/cases` queue UI, claim flow, and a functional read-only `/cases/{case_id}` detail view.

- [ ] **Step 1: Test queue query mapping without adding jsdom**

The current Vitest suite runs pure tests without jsdom. Keep tab-to-query mapping pure in `casePresentation.ts` and add:

```typescript
it("maps queue tabs to stable API filters", () => {
  expect(queryForTab("unassigned", 1)).toBe(
    "assignment=unassigned&page=1&page_size=50",
  );
  expect(queryForTab("mine", 2)).toBe(
    "assignment=mine&page=2&page_size=50",
  );
  expect(queryForTab("admin-decisions", 1)).toContain(
    "status=pending_approval&status=pending_void",
  );
  expect(queryForTab("completed", 1)).toContain(
    "status=approved&status=voided",
  );
});
```

- [ ] **Step 2: Implement queue tabs and query keys**

Use tabs `Unassigned`, `My work`, `Admin decisions`, and `Completed`. `Admin decisions` requests both `pending_approval` and `pending_void`; `Completed` requests both `approved` and `voided`. Build the TanStack Query key as `['reconciliation-cases', tab, page, invoiceNumber]` and call `/api/reconciliation-cases` with the exact Task 5 filters.

- [ ] **Step 3: Implement claim with conflict refresh**

```typescript
async function claim(item: CaseSummary) {
  try {
    const updated = await api<CaseDetail>(
      `/api/reconciliation-cases/${encodeURIComponent(item.case_id)}/claim`,
      { method: "POST", body: JSON.stringify({ expected_revision: item.revision }) },
    );
    await queryClient.invalidateQueries({ queryKey: ["reconciliation-cases"] });
    onNavigate(`/cases/${updated.case.case_id}`);
  } catch (problem) {
    if (problem instanceof ApiError &&
        ["CASE_ALREADY_CLAIMED", "CASE_REVISION_CONFLICT"].includes(problem.code ?? "")) {
      await queryClient.invalidateQueries({ queryKey: ["reconciliation-cases"] });
    }
    setError(problem instanceof Error ? problem.message : "Claim failed");
  }
}
```

- [ ] **Step 4: Add a read-only Case detail and routing**

Create `CaseDetailPage` that fetches `GET /api/reconciliation-cases/{case_id}` and renders the immutable Invoice/Receive Note numbers, summary, Case status, assignee, Items, and Action history without mutation controls. Add a `Cases` navigation button. Match `/cases/([^/]+)` before the queue path and pass decoded `caseId`, current `user`, and `navigate` into the detail page. Preserve all existing Upload, Review, and Reconcile routes.

- [ ] **Step 5: Style cards, tabs, filters, pagination, and empty/error states**

Reuse existing color variables, button styles, `.status`, `.error-banner`, and `.empty-state`. Add responsive Case cards without changing unrelated review/reconciliation layout.

- [ ] **Step 6: Document queue operation and run frontend checks**

Run from `frontend`:

```powershell
npm test -- --run
npm run build
```

Expected: all tests PASS and Vite production build succeeds.

- [ ] **Step 7: Commit the queue slice**

```powershell
git add frontend/src/cases/CaseQueuePage.tsx frontend/src/cases/CaseDetailPage.tsx frontend/src/cases/casePresentation.ts frontend/src/cases/casePresentation.test.ts frontend/src/app/App.tsx frontend/src/styles.css docs/operations/08-api-ui-and-local-run.md
git commit -m "feat: add reconciliation case queue"
```

---

### Task 8: Build Case Detail, Resolution, Audit, and Admin Decisions

**Files:**
- Modify: `frontend/src/cases/CaseDetailPage.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `docs/business/06-reconciliation-rules.md`
- Modify: `docs/reference/15-glossary.md`

**Interfaces:**
- Consumes: Task 5 detail/mutation endpoints and Task 6 permission helpers.
- Produces: full Reviewer and Admin Case workflow at `/cases/{case_id}`.

- [ ] **Step 1: Extend pure tests for action visibility**

```typescript
it("shows admin actions only in matching pending states", () => {
  expect(adminActions(caseWithStatus("pending_approval"), admin())).toEqual(["approve", "return"]);
  expect(adminActions(caseWithStatus("pending_void"), admin())).toEqual(["void", "return"]);
  expect(adminActions(caseWithStatus("approved"), admin())).toEqual([]);
});
```

- [ ] **Step 2: Render immutable reconciliation and actionable items**

Show Invoice/Receive Note numbers, PO/currency flags, summary counts, and all line results. Visually separate actionable Case Items from exact/tolerance read-only lines. Never send edited Reconciliation JSON back to the server.

- [ ] **Step 3: Implement assigned Reviewer resolution editing**

Each Item uses the four exact resolution values and a required note textarea. Save one Item at a time with the latest `detail.case.revision`; after success, replace cached detail with the response. Disable controls for non-assignees and terminal states.

```typescript
async function saveResolution(itemId: string, resolution: ResolutionType, note: string) {
  const updated = await api<CaseDetail>(
    `/api/reconciliation-cases/${encodeURIComponent(caseId)}/items/${encodeURIComponent(itemId)}/resolution`,
    {
      method: "PUT",
      body: JSON.stringify({
        resolution_type: resolution,
        note: note.trim(),
        expected_revision: detail.case.revision,
      }),
    },
  );
  queryClient.setQueryData(["reconciliation-case", caseId], updated);
}
```

- [ ] **Step 4: Implement submit approval/void rules**

Use `availableSubmission(items)` only for button presentation. The server remains authoritative. Call `submit-approval` only for `approval`, `submit-void` only for `void`, and show a specific explanation when unresolved or waiting items block submission.

Use one mutation helper for transition endpoints:

```typescript
async function transition(action: "submit-approval" | "submit-void" | "approve" | "void") {
  const updated = await api<CaseDetail>(
    `/api/reconciliation-cases/${encodeURIComponent(caseId)}/${action}`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_revision: detail.case.revision,
      }),
    },
  );
  queryClient.setQueryData(["reconciliation-case", caseId], updated);
}
```

- [ ] **Step 5: Implement Admin reassign, approve, return, and void**

Load active Reviewer choices from `GET /api/reconciliation-cases/assignees`. Admin reassign requires a selected Reviewer user ID and non-empty reason. Return requires a non-empty reason modal/inline form. Approve is visible only for `pending_approval`; void only for `pending_void`. All calls include current revision.

- [ ] **Step 6: Handle revision conflicts consistently**

On `CASE_REVISION_CONFLICT`, refetch detail and display “This Case changed while you were viewing it. The latest version has been loaded.” Do not automatically replay the failed mutation. Other errors display the server message without discarding unsaved textarea content.

- [ ] **Step 7: Render append-only audit history**

Order Actions as returned by the API and display actor, timestamp, action label, reason, and old/new resolution values. `approved` and `voided` pages are fully read-only but retain CSV export access through the existing reconciliation ID.

Add an `Export CSV` button that calls the existing `/api/reconciliations/{reconciliation_id}/export.csv` through `downloadFile`; do not duplicate CSV generation in the browser.

- [ ] **Step 8: Update business/glossary docs and run frontend verification**

Run from `frontend`:

```powershell
npm test -- --run
npm run build
```

Expected: all tests PASS and production build succeeds.

- [ ] **Step 9: Commit the detail slice**

```powershell
git add frontend/src/cases/CaseDetailPage.tsx frontend/src/cases/casePresentation.ts frontend/src/cases/casePresentation.test.ts frontend/src/app/App.tsx frontend/src/styles.css docs/business/06-reconciliation-rules.md docs/reference/15-glossary.md
git commit -m "feat: add reconciliation case decisions"
```

---

### Task 9: Complete Architecture Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture/07-data-and-infrastructure.md`
- Modify: `docs/architecture/14-source-code-walkthrough.md`
- Modify: `docs/code-document-map.json`
- Modify: `docs/README.md` only if a new standalone Case document is introduced during execution; otherwise leave it unchanged.
- Modify: `tests/test_reference_documentation.py`
- Modify: `tests/test_code_comment_coverage.py` only if new critical files are governed there.

**Interfaces:**
- Consumes: all completed backend/frontend slices.
- Produces: source-backed documentation, documentation governance coverage, and a fully verified branch.

- [ ] **Step 1: Add failing documentation contract assertions**

```python
def test_case_api_is_documented() -> None:
    contracts = Path("docs/reference/11-api-contracts.md").read_text(encoding="utf-8")
    assert "/api/reconciliation-cases/{case_id}/claim" in contracts
    assert "/api/reconciliation-cases/{case_id}/approve" in contracts
    assert "CASE_REVISION_CONFLICT" in contracts
```

Add the three new backend source patterns and `frontend/src/cases/**` to the reconciliation and API/UI documentation groups in `docs/code-document-map.json`.

- [ ] **Step 2: Run documentation tests and verify any missing coverage**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_reference_documentation.py tests\test_documentation_sync.py -q`

Expected before final doc edits: FAIL on missing Case references or mappings.

- [ ] **Step 3: Complete source walkthrough and architecture documentation**

Document:

- immutable Reconciliation vs mutable Case boundary;
- atomic creation transaction;
- Case/Item/Action tables and trigger protection;
- claim and optimistic revision flow;
- Reviewer/Admin responsibilities;
- terminal immutability and replacement-Reconciliation rule.

Update README's current capabilities without claiming notifications, attachments, analytics, or production deployment.

- [ ] **Step 4: Run the complete backend suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\check_documentation_sync.py --base-ref origin/main
git diff --check
```

Expected: all tests PASS, documentation sync PASS, and no whitespace errors. The existing Starlette/httpx deprecation warning may remain; no new warnings are acceptable.

- [ ] **Step 5: Run the complete frontend suite**

Run from `frontend`:

```powershell
npm test -- --run
npm run build
```

Expected: all Vitest tests PASS and Vite production build succeeds.

- [ ] **Step 6: Run a PostgreSQL migration smoke test**

Against a disposable database configured for this project:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic downgrade 20260731_10
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Expected: each command succeeds; final current revision is `20260803_11`. Never run the downgrade against shared or user data.

- [ ] **Step 7: Perform one manual end-to-end acceptance pass**

Using synthetic project data:

1. create a mismatched Reconciliation and confirm an `unassigned` Case appears;
2. claim it as Reviewer A and confirm Reviewer B is read-only;
3. resolve all Items as `business_exception`, submit, and approve as Admin;
4. confirm terminal immutability and audit history;
5. create a second mismatch, use `document_data_error`, submit void, and void as Admin;
6. open the same Case in two sessions and confirm a stale mutation returns/reports a revision conflict;
7. create an exact Reconciliation and confirm it has no Case.

- [ ] **Step 8: Commit final documentation and verification changes**

```powershell
git add README.md docs/architecture/07-data-and-infrastructure.md docs/architecture/14-source-code-walkthrough.md docs/code-document-map.json tests/test_reference_documentation.py tests/test_code_comment_coverage.py
git commit -m "docs: complete reconciliation case workflow"
```

If `tests/test_code_comment_coverage.py` or `docs/README.md` did not require a change, omit that path from `git add` rather than creating a cosmetic edit.

---

## Completion Checklist

- [ ] Every abnormal Reconciliation creates exactly one Case in the same transaction.
- [ ] Every clean Reconciliation creates no Case.
- [ ] Two concurrent claims cannot create two assignees.
- [ ] Stale revisions cannot overwrite current Case or Item state.
- [ ] Reviewer/Admin permission and transition matrices pass.
- [ ] Every successful mutation appends exactly one immutable Action.
- [ ] `approved` and `voided` are protected in service, repository, and PostgreSQL.
- [ ] Queue, detail, read-only, approval, void, return, reassign, and conflict UI paths work.
- [ ] Backend tests, frontend tests/build, migration smoke test, documentation sync, and `git diff --check` pass.
- [ ] No out-of-scope attachments, notifications, analytics, new roles, or native `.xlsx` were added.
