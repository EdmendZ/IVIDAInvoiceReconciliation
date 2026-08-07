# Taptouch Receiving Integration Implementation Plan

> **Execution constraint:** Superpowers was used only to produce and review this plan. Implementation must proceed through the normal engineering workflow; do not invoke Superpowers implementation or code-generation skills.

**Goal:** Import authoritative Taptouch receiving records into the existing immutable document-version model so they can participate in invoice reconciliation without OCR, extraction drafts, or fake human review history.

**Architecture:** Extend `document_versions` as the single canonical version store. Uploaded documents continue through extraction and human approval; Taptouch records enter through a bearer-protected integration API, are stored as immutable upstream-authoritative receive-note versions, and are exposed to reconciliation only while active. A thin service owns payload-to-domain mapping, while a PostgreSQL repository owns atomic idempotency and version-conflict decisions.

**Technology:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL/SQLite repository tests, React/TypeScript/Vitest, pytest.

**Design source:** `docs/superpowers/specs/2026-08-07-taptouch-receiving-integration-design.md`

---

## Delivery rules

- Write the failing test before each behavioral change and run that focused test once to prove the gap.
- Keep the existing reconciliation and case state machines unchanged.
- Never manufacture `ExtractionTask`, `ExtractionRun`, `DocumentDraft`, reviewer, or `ReviewAction` rows for Taptouch data.
- Do not build PO creation, tenant administration, webhook delivery, or workflow-mode switching in this phase.
- Make each commit independently reviewable. Do not combine unrelated cleanup.
- Preserve unrelated user changes if the worktree becomes dirty.

## Task 1: Add canonical source and trust semantics to the domain

**Files:**

- Create: `app/domain/document_sources.py`
- Modify: `app/domain/document_versions.py`
- Modify: `tests/test_document_versions.py`

**Step 1: Add failing domain tests**

Add tests covering these exact invariants:

1. An uploaded invoice version requires `task_id`, `source_draft_id`, `version_number`, and `created_by`.
2. A newly created uploaded version may be `untrusted`; an approved uploaded version must be `human_approved`.
3. `taptouch_receiving` requires `document_type=receive_note`, no extraction/draft/user lineage, and every external identity field.
4. An active Taptouch record is approved and `upstream_authoritative`.
5. A Taptouch record with missing store, receiving ID, external version, record status, or upstream timestamp is rejected.
6. Upload source kind must match document type.

Run:

```powershell
pytest tests/test_document_versions.py -q
```

Expected: failures because source/trust types and fields do not exist.

**Step 2: Define source enums**

Create `app/domain/document_sources.py`:

```python
from enum import StrEnum


class DocumentSourceKind(StrEnum):
    INVOICE_UPLOAD = "invoice_upload"
    EXTERNAL_RECEIVE_NOTE_UPLOAD = "external_receive_note_upload"
    TAPTOUCH_RECEIVING = "taptouch_receiving"


class DocumentTrustMethod(StrEnum):
    HUMAN_APPROVED = "human_approved"
    UPSTREAM_AUTHORITATIVE = "upstream_authoritative"
    UNTRUSTED = "untrusted"


class UpstreamRecordStatus(StrEnum):
    ACTIVE = "active"
    VOIDED = "voided"
```

**Step 3: Extend and validate `DocumentVersion`**

Make these existing fields optional for structured imports:

```python
task_id: str | None = None
source_draft_id: str | None = None
version_number: int | None = None
created_by: str | None = None
```

Add:

```python
source_kind: DocumentSourceKind
trust_method: DocumentTrustMethod
source_system: str | None = None
external_tenant_id: str | None = None
external_brand_id: str | None = None
external_store_id: str | None = None
external_supplier_id: str | None = None
external_receiving_id: str | None = None
external_version: int | None = None
record_status: UpstreamRecordStatus | None = None
upstream_updated_at: datetime | None = None
```

Use a Pydantic `model_validator(mode="after")` to enforce the test matrix. For uploaded rows, infer nothing silently: all call sites must explicitly assign the correct source and trust. For Taptouch rows, require `source_system == "taptouch"`, `status == APPROVED`, `trust_method == UPSTREAM_AUTHORITATIVE`, `approved_by is None`, and all external fields except `external_brand_id`.

**Step 4: Run tests and commit**

```powershell
pytest tests/test_document_versions.py -q
git add app/domain/document_sources.py app/domain/document_versions.py tests/test_document_versions.py
git commit -m "feat: model document source trust semantics"
```

Expected: focused tests pass.

## Task 2: Migrate the canonical version table and preserve upload behavior

**Files:**

- Create: `alembic/versions/20260807_13_add_taptouch_receiving_source.py`
- Modify: `app/infra/database_models.py`
- Modify: `app/infra/postgres_review_repository.py`
- Modify: `tests/test_postgres_review_repository.py`
- Modify: `tests/test_migrations.py` or the repository's existing migration integration test file

**Step 1: Add failing repository tests**

Assert that:

- Creating an invoice draft version stores `source_kind=invoice_upload` and `trust_method=untrusted`.
- Creating an uploaded receive-note draft version stores `external_receive_note_upload`.
- Approval changes trust to `human_approved`; rejection leaves it `untrusted`.
- Mapping a row with nullable upload-lineage fields does not crash.

Run the focused repository test and observe failure.

**Step 2: Add ORM columns and constraints**

Update `DocumentVersionRow`:

- Make `task_id`, `source_draft_id`, `version_number`, and `created_by` nullable.
- Add all fields from Task 1 with SQL types matching their domain values.
- Add unique constraint:

```text
(source_system, external_tenant_id, external_store_id,
 external_receiving_id, external_version)
```

- Add check constraints that encode the two valid shapes:
  - upload source: lineage fields present, Taptouch identity fields absent;
  - Taptouch source: receive-note type, lineage fields absent, external fields present, approved/upstream-authoritative.
- Keep `uq_document_versions_task_version`; PostgreSQL permits multiple nulls, while upload rows still supply both fields.

**Step 3: Write reversible Alembic migration**

Migration order:

1. Add nullable source/trust/external columns.
2. Backfill `source_kind` from `document_type`.
3. Backfill `trust_method=human_approved` for approved rows and `untrusted` otherwise.
4. Make `source_kind` and `trust_method` non-null.
5. Relax upload-lineage nullability.
6. Add unique and check constraints.

Downgrade must first reject/detect Taptouch rows with an explicit migration error or delete nothing automatically; because downgrade cannot represent them safely, document that the downgrade requires removing/exporting integration rows before applying it. Do not silently destroy imported data.

**Step 4: Update review repository mapping**

- Set upload source kind based on `document.document_type` when creating versions.
- Set `trust_method=untrusted` initially.
- On approval set both `status=approved` and `trust_method=human_approved`.
- Map every new column in `_to_domain`.

**Step 5: Verify upgrade and repository tests**

```powershell
pytest tests/test_postgres_review_repository.py -q
pytest tests/test_migrations.py -q
git add alembic/versions/20260807_13_add_taptouch_receiving_source.py app/infra/database_models.py app/infra/postgres_review_repository.py tests
git commit -m "feat: persist canonical document source metadata"
```

## Task 3: Define and map the Taptouch receiving contract

**Files:**

- Create: `app/domain/taptouch_receiving.py`
- Create: `app/services/taptouch_receiving_import_service.py`
- Create: `tests/test_taptouch_receiving_import_service.py`

**Step 1: Add failing service tests**

Cover:

- A valid active payload becomes a `ReceiveNote`-backed `DocumentVersion`.
- `received_at` maps to the document business date without timezone-dependent drift.
- Supplier/location and item fields are preserved.
- A voided payload still creates an immutable version with `record_status=voided`.
- Missing/empty identifiers, currency, items, or non-positive external version fail validation.
- Service returns `created=True` or `False` exactly as reported by its repository port.

**Step 2: Add API/domain payload models**

Use one strict model (`extra="forbid"`) with:

```python
external_tenant_id: str
external_brand_id: str | None = None
external_store_id: str
external_supplier_id: str
external_receiving_id: str
external_version: int  # ge=1
record_status: UpstreamRecordStatus
document_number: str
received_at: datetime
currency: str
purchase_order_number: str | None = None
supplier: Party
location: Party
items: list[LineItem]  # min_length=1
upstream_updated_at: datetime
```

Normalize only harmless formatting (trim identifiers, uppercase currency). Do not invent missing business identifiers.

**Step 3: Define service and repository port**

```python
class TaptouchReceivingImportRepository(Protocol):
    def import_version(self, version: DocumentVersion) -> "ReceivingImportOutcome": ...


class ReceivingImportOutcome(BaseModel):
    version: DocumentVersion
    created: bool
```

The service constructs a `ReceiveNote`, then a version with:

```python
document_type = DocumentType.RECEIVE_NOTE
status = DocumentVersionStatus.APPROVED
source_kind = DocumentSourceKind.TAPTOUCH_RECEIVING
trust_method = DocumentTrustMethod.UPSTREAM_AUTHORITATIVE
source_system = "taptouch"
approved_by = None
approved_at = import_clock
```

Inject UUID and clock functions so unit tests are deterministic.

**Step 4: Run and commit**

```powershell
pytest tests/test_taptouch_receiving_import_service.py -q
git add app/domain/taptouch_receiving.py app/services/taptouch_receiving_import_service.py tests/test_taptouch_receiving_import_service.py
git commit -m "feat: map Taptouch receiving records"
```

## Task 4: Implement atomic idempotent PostgreSQL import

**Files:**

- Create: `app/infra/postgres_taptouch_receiving_repository.py`
- Create: `tests/test_postgres_taptouch_receiving_repository.py`

**Step 1: Add failing repository scenarios**

For identity `(taptouch, tenant, store, receiving)` assert:

1. First external version inserts and returns `created=True`.
2. Byte-for-byte semantic replay of the same version returns the original row and `created=False`.
3. Same external version with changed payload/metadata raises `ReceivingIdentityConflict`.
4. Lower version than the current maximum raises `ReceivingVersionConflict`.
5. Higher version inserts a new immutable row.
6. Different stores or tenants may reuse the same receiving ID.
7. No extraction/draft/review rows are created.

**Step 2: Implement conflict types and comparison**

Define typed exceptions in the service module:

```python
class ReceivingVersionConflict(Exception): ...
class ReceivingIdentityConflict(Exception): ...
```

Compare the normalized domain snapshot, external metadata, record status, and upstream timestamp. Ignore local `version_id`, `approved_at`, and `created_at` when deciding whether the same-version request is a replay.

**Step 3: Make the decision atomic**

Within one transaction:

- Query current versions for the external identity with a row lock on PostgreSQL.
- Return equal same-version row.
- Reject changed same-version or lower-version input.
- Insert higher/first version.
- Catch the unique-constraint race, reload, and apply the same comparison so concurrent identical calls converge while conflicting calls return conflict.

Keep SQLite compatibility in repository tests without pretending it provides PostgreSQL row-lock semantics; migration/PostgreSQL integration tests cover the constraint.

**Step 4: Run and commit**

```powershell
pytest tests/test_postgres_taptouch_receiving_repository.py -q
git add app/infra/postgres_taptouch_receiving_repository.py app/services/taptouch_receiving_import_service.py tests/test_postgres_taptouch_receiving_repository.py
git commit -m "feat: import Taptouch versions idempotently"
```

## Task 5: Expose the protected integration endpoint

**Files:**

- Create: `app/api/integration_auth.py`
- Create: `app/api/taptouch_integration_routes.py`
- Modify: `app/core/config.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/main.py`
- Modify: `.env.example`
- Modify: `.env.compose.example`
- Modify: `compose.yaml`
- Create: `tests/test_taptouch_integration_api.py`

**Step 1: Add failing API tests**

Test the exact HTTP contract:

- Missing/malformed/wrong bearer token -> 401.
- Valid first import -> 201 with `created=true` and canonical version metadata.
- Identical replay -> 200 with `created=false` and same version ID.
- Stale or changed same-version import -> 409 with stable machine-readable error code.
- Invalid payload -> 422.
- Unexpected persistence failure -> existing global 500 handling, without leaking the bearer token.

Use FastAPI dependency overrides for service tests; add a separate unit test that config token comparison is constant-time via `hmac.compare_digest` behavior, without logging secrets.

**Step 2: Add configuration and auth dependency**

In `Settings`:

```python
taptouch_integration_token: str = Field(default="", repr=False)
```

The auth dependency uses `HTTPBearer(auto_error=False)`. Treat an empty configured token as disabled and return 401. Never echo or log the supplied token.

**Step 3: Add route and dependency wiring**

Endpoint:

```text
POST /api/integrations/taptouch/receiving-records
```

Response codes are selected from `ReceivingImportOutcome.created`. Map typed conflicts to 409 response bodies such as:

```json
{"detail": {"code": "stale_external_version", "message": "..."}}
```

Register repository/service factories in `app/api/dependencies.py` and include the router in `app/main.py`.

**Step 4: Wire local/Compose configuration**

- Document `TAPTOUCH_INTEGRATION_TOKEN` in both env examples.
- Pass it into the API container in `compose.yaml` without committing a real secret.

**Step 5: Run and commit**

```powershell
pytest tests/test_taptouch_integration_api.py -q
git add app/api app/core/config.py app/main.py .env.example .env.compose.example compose.yaml tests/test_taptouch_integration_api.py
git commit -m "feat: expose Taptouch receiving import API"
```

## Task 6: Gate reconciliation by source trust and surface provenance

**Files:**

- Modify: `app/infra/postgres_review_repository.py`
- Modify: `app/services/reconciliation_application_service.py`
- Modify: `app/domain/reconciliation.py`
- Modify: `app/api/routes.py`
- Modify: `app/api/review_routes.py`
- Modify: `tests/test_reconciliation_gate.py`
- Modify: `tests/test_candidate_matching_service.py`
- Modify: relevant reconciliation/review API tests

**Step 1: Add failing trust-gate tests**

Assert:

- Approved + human-approved upload is eligible.
- Approved + upstream-authoritative + active Taptouch version is eligible.
- Draft/rejected/untrusted versions are ineligible.
- Voided Taptouch versions are ineligible even though stored as approved immutable history.
- A newer voided version suppresses all older active versions of the same external identity.
- Candidate JSON includes source kind, trust method, store, receiving ID, external version, and upstream update time.

The “newer void suppresses older active” rule is essential: eligibility must select the latest external version per identity first, then evaluate active/voided status.

**Step 2: Centralize repository eligibility**

Keep the existing method name if that minimizes callers, but make its contract explicit: a reconciliation-readable version must be approved, trusted, and currently active. For Taptouch identities, query only the latest `external_version`. Do not allow the service to reconstruct this rule from an unscoped list.

**Step 3: Extend candidate source context**

Add optional fields to `ReconciliationCandidate` for upload compatibility:

```python
source_kind: DocumentSourceKind
trust_method: DocumentTrustMethod
external_store_id: str | None
external_receiving_id: str | None
external_version: int | None
upstream_updated_at: datetime | None
```

Pass context from the selected `DocumentVersion`; do not embed integration metadata in the business document JSON.

**Step 4: Update review/version API schema**

Return nullable `version_number` and `approved_at`, plus canonical source metadata. Existing uploaded responses retain their previous values.

**Step 5: Run and commit**

```powershell
pytest tests/test_reconciliation_gate.py tests/test_candidate_matching_service.py -q
pytest tests -q -k "reconciliation or approved_version"
git add app/domain app/infra/postgres_review_repository.py app/services/reconciliation_application_service.py app/api tests
git commit -m "feat: reconcile trusted receiving sources"
```

## Task 7: Show source provenance in the frontend

**Files:**

- Create: `frontend/src/reconcile/reconciliationTypes.ts`
- Modify: `frontend/src/reconcile/ReconciliationPage.tsx`
- Modify: `frontend/src/upload/UploadPage.tsx`
- Modify: `frontend/src/styles.css`
- Modify/Create: frontend Vitest files following existing test layout

**Step 1: Add failing UI tests**

Cover:

- Taptouch candidate renders badge `Taptouch Receiving`.
- Store ID, external receiving ID, external version, and upstream time render when present.
- Uploaded receive note renders `Uploaded Receive Note` and hides empty external metadata.
- Reconciliation copy says trusted immutable versions, not human-approved-only versions.
- Upload page explains Taptouch Receiving records sync automatically and file upload is for invoices/external receive notes.

**Step 2: Extract shared response types**

Move the page-local API types into `reconciliationTypes.ts`. Make `version_number`, `approved_at`, and integration fields nullable as defined by the backend.

**Step 3: Add small provenance component/markup**

Map source values to stable user labels:

```text
invoice_upload -> Uploaded Invoice
external_receive_note_upload -> Uploaded Receive Note
taptouch_receiving -> Taptouch Receiving
```

Change the eyebrow from `THREE-WAY CONTROL` to `RECEIVING CONTROL`; this phase is invoice-versus-receiving reconciliation and does not implement a full three-way PO control.

**Step 4: Run and commit**

```powershell
Set-Location frontend
npm test -- --run
npm run build
Set-Location ..
git add frontend/src
git commit -m "feat: display receiving source provenance"
```

## Task 8: Document product positioning, operations, and contract

**Files:**

- Create: `docs/business/00-product-positioning.md`
- Create: `docs/business/02-taptouch-receiving-integration.md`
- Create: `docs/business/08-product-gaps-and-roadmap.md`
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: relevant existing files under `docs/business/`
- Modify: API contract documentation used by this repository
- Modify: database dictionary documentation used by this repository
- Modify: `docs/code-document-map.json`
- Modify: `tests/test_documentation_sync.py`
- Modify: `tests/test_reference_documentation.py`

**Step 1: Add/update documentation checks first**

Require documentation to mention:

- the new endpoint;
- all new `document_versions` columns;
- bearer-token environment variable;
- source/trust eligibility rules;
- local example import command;
- IVIDA/Taptouch positioning and Zeemart's reference-only role.

**Step 2: Write business documentation**

`00-product-positioning.md` must state:

- this repository is a Taptouch Back Office extension/prototype;
- Taptouch structured receiving is authoritative and bypasses OCR;
- OCR/LLM remains for external supplier invoices and uploaded compatibility documents;
- PO number is an optional matching signal, not a locally owned PO subsystem.

`02-taptouch-receiving-integration.md` must document:

- payload example;
- idempotency/version semantics;
- auth and status codes;
- active/void behavior;
- local curl/PowerShell invocation;
- no fake review lineage.

`08-product-gaps-and-roadmap.md` must separate shipped phase 1 from later work:

- tenant/store authorization boundaries;
- duplicate-invoice detection;
- partial receiving allocation;
- simple/enterprise workflow modes;
- webhook/event delivery and credential rotation.

**Step 3: Update technical references and map**

- Add new source files to a documentation-map group owned by the Taptouch integration doc.
- Update database dictionary to match ORM columns exactly.
- Update API contract with 200/201/401/409/422 behavior.
- Add README quick-start instructions using a placeholder token only.

**Step 4: Run and commit**

```powershell
pytest tests/test_documentation_sync.py tests/test_reference_documentation.py -q
git add README.md docs tests/test_documentation_sync.py tests/test_reference_documentation.py
git commit -m "docs: explain Taptouch receiving workflow"
```

## Task 9: Full regression, local smoke test, and delivery

**Files:**

- Modify only files required to fix failures caused by this feature.

**Step 1: Run backend quality gates**

Use the repository's configured commands from `pyproject.toml`/CI. At minimum:

```powershell
pytest -q
ruff check .
mypy app
```

If command names differ, use the exact CI equivalents and record them in the delivery summary.

**Step 2: Run frontend quality gates**

```powershell
Set-Location frontend
npm test -- --run
npm run build
Set-Location ..
```

**Step 3: Run migration and local import smoke test**

With local PostgreSQL/Compose configured using a non-production placeholder token:

1. Upgrade to Alembic head.
2. Start API.
3. POST one active Taptouch receiving record -> 201.
4. Replay -> 200 with same ID.
5. Confirm it appears as a reconciliation candidate.
6. POST a higher voided version.
7. Confirm it no longer appears as a candidate.
8. Confirm no extraction task, draft, or review action was created.

Do not commit local secrets, `.env`, database volumes, or generated runtime files.

**Step 4: Inspect the final diff**

```powershell
git status --short
git diff main...HEAD --stat
git diff main...HEAD --check
git log --oneline main..HEAD
```

Confirm every design requirement is represented by code, tests, or documentation, and no PO subsystem or workflow-mode feature slipped into scope.

**Step 5: Commit any narrowly scoped verification fixes**

```powershell
git add <only-the-files-fixed>
git commit -m "fix: complete Taptouch integration verification"
```

Skip this commit if verification required no changes.

## Acceptance checklist

- [ ] Existing upload/review flow behaves exactly as before.
- [ ] Taptouch import never creates extraction or review lineage.
- [ ] First import is 201; identical replay is 200; stale or conflicting version is 409.
- [ ] Canonical document-version constraints reject invalid source combinations.
- [ ] Reconciliation accepts human-approved uploads and active upstream-authoritative records only.
- [ ] A latest voided version suppresses older active versions.
- [ ] UI clearly identifies provenance and does not claim full three-way matching.
- [ ] API, database, business, code-map, and setup documentation are synchronized.
- [ ] Backend tests, lint/type checks, frontend tests/build, and migration smoke test pass.
- [ ] No real integration token or server credential is committed.

