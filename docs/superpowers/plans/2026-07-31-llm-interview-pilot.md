# LLM Interview Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a stable five-minute invoice-to-receive-note demonstration plus a reproducible, evidence-backed evaluation of the MinerU and LLM normalization pipeline.

**Architecture:** Keep the existing modular FastAPI application, PostgreSQL task queue, independent extraction Worker, MinIO artifact storage and React UI. Add only the reliability required for a deterministic local demonstration, then build an offline evaluation runner that reuses cached MinerU parse results so prompt and model variants can be compared without repeatedly paying for OCR.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, MinIO, MinerU API, OpenAI-compatible chat API, React 19, TypeScript, Vite, Vitest, pytest, PowerShell.

## Global Constraints

- Present the project as a **可审计的 AI 辅助审核 Pilot**, not a production-grade or highly available platform.
- MinerU and the LLM extract fields and evidence; deterministic Python rules make reconciliation decisions.
- Human approval remains mandatory before the production-path reconciliation API accepts a document version.
- Use only the synthetic Australian pizza procurement dataset under `evaluation_data/`.
- Never write API tokens, document contents or provider response bodies to logs or tracked files.
- Cache MinerU results by source SHA-256 so normalization experiments do not repeat OCR calls.
- Store generated evaluation results under ignored `evaluation_data/results/`.
- Keep one Worker process for the interview demo.
- Multi-worker fencing, four-eyes approval, HA, container orchestration, malware scanning and full retention governance are excluded from this plan and remain enterprise-hardening work.
- Every backend task follows red-green-refactor testing and ends with a focused commit.
- Frontend behavior added by this plan requires Vitest coverage.

---

### Task 1: Close the Demonstration API Governance Gaps

**Files:**
- Modify: `app/api/upload_routes.py`
- Modify: `app/api/extraction_routes.py`
- Modify: `app/api/routes.py`
- Modify: `tests/test_upload_api.py`
- Modify: `tests/test_extraction_result_api.py`
- Create: `tests/test_route_governance.py`

**Interfaces:**
- Consumes: `require_reviewer()` from `app/api/auth_dependencies.py`.
- Produces: authenticated upload, extraction and reconciliation routes; development-only raw comparison routes.

- [ ] **Step 1: Write failing authentication tests**

```python
def test_upload_requires_reviewer(client) -> None:
    response = client.post(
        "/api/documents/upload",
        data={"document_type": "invoice"},
        files={"file": ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")},
    )
    assert response.status_code == 401


def test_extraction_result_requires_reviewer(client) -> None:
    response = client.get("/api/extraction-runs/run-1/result")
    assert response.status_code == 401
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_route_governance.py -q
```

Expected: both requests currently pass the authentication boundary or reach a downstream dependency instead of returning `401`.

- [ ] **Step 3: Add the reviewer dependency to all business routes**

Add this dependency to upload, task lookup, extraction start, run lookup and result lookup:

```python
user: AuthenticatedUser = Depends(require_reviewer),
```

The handler may use `del user` when the actor is not persisted yet.

- [ ] **Step 4: Register diagnostic reconciliation routes only in development**

Split the raw example and raw JSON compare endpoints into a `diagnostic_router`, then include it from `app/main.py` only when:

```python
if settings.app_env.lower() == "dev":
    app.include_router(diagnostic_router)
```

Keep authenticated approved-version reconciliation on the normal router.

- [ ] **Step 5: Run the backend suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass and unauthenticated business calls return `401`.

- [ ] **Step 6: Commit**

```powershell
git add app/api app/main.py tests
git commit -m "fix: protect financial document routes"
```

---

### Task 2: Expose Worker Liveness for Honest Queue Status

**Files:**
- Create: `migrations/versions/20260731_08_add_worker_heartbeats.py`
- Create: `app/domain/worker_runtime.py`
- Create: `app/infra/postgres_worker_runtime_repository.py`
- Create: `app/services/runtime_status_service.py`
- Modify: `app/infra/database_models.py`
- Modify: `app/services/ports.py`
- Modify: `app/api/dependencies.py`
- Create: `app/api/runtime_routes.py`
- Modify: `app/main.py`
- Modify: `run_extraction_worker.py`
- Modify: `app/workers/extraction_worker.py`
- Create: `tests/test_worker_runtime_repository.py`
- Create: `tests/test_runtime_api.py`

**Interfaces:**
- Produces:

```python
class WorkerRuntimeRepository(Protocol):
    def heartbeat(
        self,
        *,
        worker_id: str,
        version: str,
        now: datetime,
    ) -> None: ...

    def latest(self) -> WorkerHeartbeat | None: ...
```

- Produces: authenticated `GET /api/runtime/status`.

- [ ] **Step 1: Write the heartbeat expiry test**

```python
def test_runtime_marks_stale_worker_offline(runtime_service, clock) -> None:
    runtime_service.record_heartbeat(
        worker_id="demo-worker",
        version="0.1.0",
        now=clock.now(),
    )
    result = runtime_service.status(now=clock.now() + timedelta(seconds=31))
    assert result.worker == "offline"
```

- [ ] **Step 2: Run the test and verify the runtime types are missing**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_worker_runtime_repository.py -q
```

Expected: import failure for `app.domain.worker_runtime`.

- [ ] **Step 3: Add the heartbeat table and domain model**

Use one row per `worker_id` with `started_at`, `last_seen_at` and `version`. Use PostgreSQL server time for persisted heartbeats. Define the API response as:

```python
class RuntimeStatus(BaseModel):
    api: Literal["up"]
    database: Literal["up", "down"]
    minio: Literal["up", "down", "degraded"]
    worker: Literal["online", "offline"]
    worker_last_seen_at: datetime | None
```

Do not return hostnames, endpoints, bucket names or exception text.

- [ ] **Step 4: Send heartbeats from the Worker loop**

Extend `ExtractionWorker.run_forever()` with an injected runtime repository and a heartbeat interval of 10 seconds. Heartbeat failures must be logged with a stable code and must not discard queued work.

- [ ] **Step 5: Add the authenticated runtime endpoint**

```python
@router.get("/runtime/status", response_model=RuntimeStatus)
def runtime_status(
    user: AuthenticatedUser = Depends(require_reviewer),
    service: RuntimeStatusService = Depends(get_runtime_status_service),
) -> RuntimeStatus:
    del user
    return service.status()
```

- [ ] **Step 6: Apply the migration and run tests**

Run:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m pytest tests/test_worker_runtime_repository.py tests/test_runtime_api.py -q
```

Expected: runtime endpoint reports `offline` with no recent heartbeat and `online` after a heartbeat.

- [ ] **Step 7: Commit**

```powershell
git add migrations app tests
git commit -m "feat: expose extraction worker liveness"
```

---

### Task 3: Add Cooperative Task Cancellation

**Files:**
- Create: `migrations/versions/20260731_09_add_extraction_cancellation.py`
- Modify: `app/domain/extraction_runs.py`
- Modify: `app/infra/database_models.py`
- Modify: `app/services/ports.py`
- Modify: `app/infra/postgres_extraction_run_repository.py`
- Modify: `app/services/extraction_service.py`
- Modify: `app/workers/extraction_worker.py`
- Modify: `app/api/extraction_routes.py`
- Modify: `tests/fakes.py`
- Create: `tests/test_extraction_cancellation.py`
- Modify: `tests/test_extraction_worker.py`

**Interfaces:**
- Produces:

```python
def request_cancel(
    self,
    run_id: str,
    *,
    requested_by: str,
    requested_at: datetime,
) -> ExtractionRun: ...

def is_cancel_requested(self, run_id: str) -> bool: ...
```

- Produces: `POST /api/extraction-runs/{run_id}/cancel`.

- [ ] **Step 1: Write failing cancellation state tests**

```python
def test_queued_run_cancels_immediately(service, queued_run, reviewer) -> None:
    result = service.cancel(queued_run.run_id, requested_by=reviewer.user_id)
    assert result.status == ExtractionRunStatus.CANCELLED
    assert result.cancel_requested_by == reviewer.user_id


def test_cancelled_run_does_not_create_draft(worker, cancelled_run, drafts) -> None:
    worker.run_once("worker-a")
    assert drafts.get_for_run(cancelled_run.run_id) is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_extraction_cancellation.py -q
```

Expected: `CANCELLED` and cancellation repository methods do not exist.

- [ ] **Step 3: Add cancellation fields and conditional updates**

Add:

```python
cancel_requested_at: datetime | None
cancel_requested_by: str | None
cancel_completed_at: datetime | None
cancelled_stage: str | None
remote_may_continue: bool
```

Queued runs transition directly to `cancelled`. Parsing or normalizing runs record the request and transition at the next Worker boundary. Terminal runs return `409`.

- [ ] **Step 4: Check cancellation at Worker stage boundaries**

Call `is_cancel_requested(run_id)`:

1. before MinerU submission;
2. after MinerU poll returns;
3. before normalization;
4. after normalization and before draft creation.

When a remote job was already submitted, set `remote_may_continue=True`.

- [ ] **Step 5: Add the authenticated idempotent API**

The first request returns `202` for cooperative cancellation or `200` for immediate cancellation. Repeating the request returns the same cancellation state. Completed, ready-for-review and failed runs return `409`.

- [ ] **Step 6: Run migration and cancellation tests**

Run:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m pytest tests/test_extraction_cancellation.py tests/test_extraction_worker.py -q
```

Expected: a cancelled run never creates a review draft.

- [ ] **Step 7: Commit**

```powershell
git add migrations app tests
git commit -m "feat: add cooperative extraction cancellation"
```

---

### Task 4: Make the Local Demo One Command

**Files:**
- Create: `scripts/local_demo_common.ps1`
- Create: `start_local_demo.ps1`
- Create: `stop_local_demo.ps1`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `docs/operations/review-workflow.md`
- Create: `tests/powershell/start_local_demo.Tests.ps1`

**Interfaces:**
- Produces: `.local-demo/processes.json`, ignored by Git.
- Produces: logs under ignored `logs/local-demo/`.

- [ ] **Step 1: Write Pester tests for safe PID ownership**

```powershell
It "does not stop a process whose command does not match the recorded project" {
    $record = @{ pid = $PID; command = "other-app"; project_root = "C:\other" }
    Test-IvidaOwnedProcess $record | Should -BeFalse
}
```

- [ ] **Step 2: Run the Pester test and verify the helper is missing**

Run:

```powershell
Invoke-Pester tests/powershell/start_local_demo.Tests.ps1
```

Expected: failure because `Test-IvidaOwnedProcess` is undefined.

- [ ] **Step 3: Implement configuration and dependency preflight**

The shared script must verify:

- `.env` exists;
- `.venv\Scripts\python.exe` exists;
- `frontend\node_modules` exists;
- ports `8200` and `5274` are available or owned by a recorded IVIDA process;
- `GET /api/health` responds after API start;
- no secret values are printed.

- [ ] **Step 4: Start API, Worker and frontend with owned process records**

Each record contains:

```json
{
  "component": "worker",
  "pid": 1234,
  "started_at": "2026-07-31T09:00:00Z",
  "command": "run_extraction_worker.py",
  "project_root": "E:\\ZephyrLLM\\Projects\\IVIDAInvoiceReconciliation"
}
```

- [ ] **Step 5: Implement safe stop and partial-start rollback**

Stop only when PID, command signature and project root all match. If frontend startup fails, stop only processes created by the current invocation.

- [ ] **Step 6: Perform a local smoke test**

Run:

```powershell
.\start_local_demo.ps1
Invoke-WebRequest http://127.0.0.1:8200/api/health
.\stop_local_demo.ps1
```

Expected: health returns `200`; stop leaves unrelated processes untouched.

- [ ] **Step 7: Commit**

```powershell
git add scripts start_local_demo.ps1 stop_local_demo.ps1 .gitignore README.md docs tests/powershell
git commit -m "feat: add safe local demo launcher"
```

---

### Task 5: Record LLM and Prompt Provenance

**Files:**
- Create: `migrations/versions/20260731_10_add_model_provenance.py`
- Modify: `app/domain/normalization.py`
- Modify: `app/domain/extraction_runs.py`
- Modify: `app/infra/database_models.py`
- Modify: `app/infra/openai_normalization_provider.py`
- Modify: `app/infra/postgres_extraction_run_repository.py`
- Modify: `app/workers/extraction_worker.py`
- Create: `app/services/prompt_version.py`
- Create: `tests/test_prompt_version.py`
- Modify: `tests/test_normalization_provider.py`
- Modify: `tests/test_extraction_worker.py`

**Interfaces:**
- Produces:

```python
def prompt_version(*prompt_texts: str) -> str:
    """Return sha256:<first 16 lowercase hex characters>."""
```

- Extends `NormalizationResult` with `provider_name`, `model_name` and `prompt_version`.

- [ ] **Step 1: Write the prompt fingerprint test**

```python
def test_prompt_version_is_stable_and_content_addressed() -> None:
    first = prompt_version("system", "user")
    second = prompt_version("system", "user")
    changed = prompt_version("system changed", "user")
    assert first == second
    assert first.startswith("sha256:")
    assert changed != first
```

- [ ] **Step 2: Run the test and verify the function is missing**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prompt_version.py -q
```

Expected: import failure.

- [ ] **Step 3: Add model provenance to normalization results and runs**

Persist these fields on every successful or failed normalization attempt:

- parser provider and model;
- normalizer provider and model;
- prompt version;
- input/output tokens;
- estimated AUD cost;
- normalization latency.

Do not store the API base URL or token.

- [ ] **Step 4: Add the fingerprint to the OpenAI-compatible provider**

Compute the fingerprint once in `OpenAINormalizationProvider.__init__()` from the exact system prompt and user template loaded from disk.

- [ ] **Step 5: Run migration and focused tests**

Run:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m pytest tests/test_prompt_version.py tests/test_normalization_provider.py tests/test_extraction_worker.py -q
```

Expected: persisted runs identify the exact model and prompt version used.

- [ ] **Step 6: Commit**

```powershell
git add migrations app tests
git commit -m "feat: persist extraction model provenance"
```

---

### Task 6: Build Cached Extraction Evaluation

**Files:**
- Create: `app/evaluation/__init__.py`
- Create: `app/evaluation/models.py`
- Create: `app/evaluation/field_metrics.py`
- Create: `app/evaluation/cache.py`
- Create: `app/evaluation/runner.py`
- Create: `app/cli/evaluate_extraction.py`
- Create: `tests/test_evaluation_metrics.py`
- Create: `tests/test_evaluation_cache.py`
- Create: `tests/test_evaluation_runner.py`
- Modify: `.gitignore`
- Modify: `docs/evaluation-dataset.md`

**Interfaces:**
- Produces:

```python
class EvaluationVariant(BaseModel):
    name: str
    normalizer_model: str
    prompt_version: str


class DocumentEvaluation(BaseModel):
    case_id: str
    document_path: str
    document_type: DocumentType
    schema_valid: bool
    field_correct: int
    field_total: int
    evidence_covered: int
    evidence_total: int
    latency_ms: int
    estimated_cost_aud: Decimal | None


def evaluate_document(
    *,
    case_id: str,
    document_path: str,
    document_type: DocumentType,
    predicted: dict,
    gold: dict,
    evidence_paths: set[str],
) -> DocumentEvaluation: ...
```

- [ ] **Step 1: Write metric tests for scalar and line-item fields**

```python
def test_metrics_match_decimal_strings_and_lines_by_sku() -> None:
    gold = {
        "total": "378.84",
        "items": [{"sku": "FLOUR-12.5", "quantity": "8"}],
    }
    predicted = {
        "total": "378.840",
        "items": [{"sku": "FLOUR-12.5", "quantity": 8}],
    }
    result = compare_documents(predicted, gold)
    assert result.correct == result.total
```

- [ ] **Step 2: Run the metric tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation_metrics.py -q
```

Expected: evaluation package is missing.

- [ ] **Step 3: Implement deterministic field metrics**

Rules:

- compare decimal-compatible values as `Decimal`;
- compare currency and identifiers case-insensitively after whitespace normalization;
- pair line items by SKU, falling back to normalized description;
- count missing and hallucinated line items separately;
- calculate schema-valid rate, field micro accuracy, document exact-match rate, line-item F1 and evidence coverage.

- [ ] **Step 4: Implement SHA-256 MinerU cache**

Use:

```text
evaluation_data/cache/mineru/<source_sha256>.json
evaluation_data/cache/mineru/<source_sha256>.zip
```

The JSON stores parser provider, parser model, source SHA-256, Markdown, blocks, tables and page count. A cache hit must not call MinerU.

- [ ] **Step 5: Implement the evaluation runner**

The CLI command:

```powershell
.\.venv\Scripts\python.exe -m app.cli.evaluate_extraction `
  --manifest evaluation_data/manifest.json `
  --variant baseline `
  --max-documents 17
```

writes:

```text
evaluation_data/results/<evaluation_run_id>/documents.jsonl
evaluation_data/results/<evaluation_run_id>/summary.json
```

It never approves documents or writes to production review tables.

- [ ] **Step 6: Run evaluation unit tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation_metrics.py tests/test_evaluation_cache.py tests/test_evaluation_runner.py -q
```

Expected: cache hits make zero parser calls and summary aggregation is deterministic.

- [ ] **Step 7: Commit**

```powershell
git add app/evaluation app/cli tests .gitignore docs/evaluation-dataset.md
git commit -m "feat: add cached document extraction evaluation"
```

---

### Task 7: Compare Prompt and Model Variants with Error Analysis

**Files:**
- Create: `app/evaluation/variants.py`
- Create: `app/evaluation/report.py`
- Modify: `app/evaluation/models.py`
- Create: `evaluation_variants.example.json`
- Create: `tests/test_evaluation_variants.py`
- Create: `tests/test_evaluation_report.py`
- Modify: `app/cli/evaluate_extraction.py`
- Modify: `README.md`

**Interfaces:**
- Produces:

```python
class EvaluationSummary(BaseModel):
    variant_name: str
    field_micro_accuracy: Decimal
    line_item_f1: Decimal
    evidence_coverage: Decimal
    reconciliation_decision_accuracy: Decimal
    p50_latency_ms: int
    p95_latency_ms: int
    average_cost_aud: Decimal | None


class RankedVariant(BaseModel):
    name: str
    within_budget: bool
    rank: int
    rationale: list[str]


def rank_variants(
    summaries: list[EvaluationSummary],
    *,
    max_cost_aud_per_document: Decimal,
) -> list[RankedVariant]: ...
```

- Produces Markdown and JSON comparison reports.

- [ ] **Step 1: Write the cost-aware ranking test**

```python
def test_ranker_prefers_accuracy_then_cost_within_budget() -> None:
    ranked = rank_variants(
        [accurate_expensive, accurate_cheap, inaccurate_cheap],
        max_cost_aud_per_document=Decimal("0.10"),
    )
    assert ranked[0].name == "accurate-cheap"
```

- [ ] **Step 2: Run the tests and verify report code is missing**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation_variants.py tests/test_evaluation_report.py -q
```

Expected: import failure.

- [ ] **Step 3: Define variant configuration without secrets**

`evaluation_variants.example.json` contains names, models, prompt file paths and public cost rates. API keys remain environment variables.

- [ ] **Step 4: Generate comparison and error slices**

The report must include:

- schema-valid rate;
- field micro accuracy;
- document exact-match rate;
- line-item F1;
- evidence coverage;
- reconciliation decision accuracy;
- P50/P95 latency;
- average and total estimated AUD cost;
- errors grouped by document type, field path and business scenario.

The recommendation states the measured dataset boundary and never claims customer ROI.

- [ ] **Step 5: Run two variants against cached parses**

Run:

```powershell
.\.venv\Scripts\python.exe -m app.cli.evaluate_extraction `
  --manifest evaluation_data/manifest.json `
  --variants evaluation_variants.local.json `
  --reuse-mineru-cache
```

Expected: MinerU cache is reused and one comparison Markdown report is produced under the ignored results directory.

- [ ] **Step 6: Commit**

```powershell
git add app/evaluation app/cli evaluation_variants.example.json tests README.md
git commit -m "feat: compare normalization model variants"
```

---

### Task 8: Show Runtime and Model Evidence in the UI

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/runtime/types.ts`
- Create: `frontend/src/runtime/RuntimeBanner.tsx`
- Create: `frontend/src/runtime/RuntimeBanner.test.tsx`
- Create: `frontend/src/upload/taskPresentation.ts`
- Create: `frontend/src/upload/taskPresentation.test.ts`
- Modify: `frontend/src/upload/UploadPage.tsx`
- Modify: `frontend/src/review/ReviewDocumentPage.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Consumes: `GET /api/runtime/status`.
- Consumes: extraction result provenance from Task 5.
- Consumes: `POST /api/extraction-runs/{run_id}/cancel`.

- [ ] **Step 1: Add frontend test dependencies**

Add `jsdom`, `@testing-library/react` and `@testing-library/jest-dom`, and configure Vitest with `environment: "jsdom"` and a setup file.

- [ ] **Step 2: Write failing status presentation tests**

```tsx
it("explains queued tasks when the worker is offline", () => {
  render(<RuntimeBanner status={{ worker: "offline" }} />);
  expect(screen.getByText(/等待处理服务启动/i)).toBeInTheDocument();
});
```

```ts
expect(presentTaskStatus("queued", false).label).toBe("等待处理服务启动");
expect(presentTaskStatus("queued", true).label).toBe("排队处理中");
```

- [ ] **Step 3: Run Vitest and verify the components are missing**

Run:

```powershell
Set-Location frontend
npm test -- --run
```

Expected: missing component/module failures.

- [ ] **Step 4: Add runtime banner, status mapping and cancel action**

Show:

- Worker online/offline;
- parsing, normalization and review-ready business labels;
- Cancel only for queued, parsing and normalizing runs;
- `remote_may_continue` explanation after cooperative cancellation.

- [ ] **Step 5: Add model provenance to Review**

Display parser model, normalizer model, prompt version, tokens, latency and estimated cost in a collapsible “Model run” panel beside evidence. Do not display endpoint or provider credentials.

- [ ] **Step 6: Run frontend tests and build**

Run:

```powershell
npm test -- --run
npm run build
```

Expected: tests pass and Vite production build succeeds.

- [ ] **Step 7: Commit**

```powershell
git add frontend
git commit -m "feat: explain runtime and model evidence in review UI"
```

---

### Task 9: Produce the Five-Minute Interview Demonstration

**Files:**
- Create: `docs/interview/project-story.md`
- Create: `docs/interview/demo-script.md`
- Create: `docs/interview/architecture.md`
- Create: `docs/interview/evaluation-report.sample.md`
- Modify: `README.md`
- Create: `tests/test_interview_docs.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a truthful interview narrative and reproducible demonstration checklist.

- [ ] **Step 1: Write documentation contract tests**

```python
def test_interview_docs_do_not_claim_unimplemented_production_properties() -> None:
    text = Path("docs/interview/project-story.md").read_text(encoding="utf-8")
    forbidden = ["生产级", "高可用平台", "完全自动审批", "三方对账"]
    assert not any(term in text for term in forbidden)
```

- [ ] **Step 2: Write the project story**

Use this narrative:

1. one Invoice may correspond to multiple Receive Notes;
2. MinerU parses layout, LLM normalizes fields and evidence;
3. deterministic rules validate and reconcile;
4. human approval gates the financial result;
5. PostgreSQL and MinIO preserve auditability;
6. evaluation compares accuracy, evidence, latency and cost.

- [ ] **Step 3: Write the five-minute demo script**

The script demonstrates:

1. one-command startup;
2. Worker-offline queued explanation and recovery;
3. upload one Invoice and two split-delivery Receive Notes;
4. evidence-backed field review;
5. one validation issue corrected before approval;
6. explainable candidate recommendation;
7. final line-level reconciliation;
8. one evaluation comparison result.

- [ ] **Step 4: Add the architecture and measured-results boundary**

State clearly:

- implemented Pilot capabilities;
- synthetic dataset size and scenarios;
- measured metrics;
- unimplemented enterprise hardening;
- why PostgreSQL polling was selected instead of adding a message broker.

- [ ] **Step 5: Run complete verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
npm test -- --run
npm run build
```

Expected: backend tests, frontend tests and build all pass.

- [ ] **Step 6: Perform the manual demo once and record evidence**

Save screenshots that contain no credentials or real financial data under `docs/interview/screenshots/`. Record the exact evaluation run ID used by `evaluation-report.sample.md`.

- [ ] **Step 7: Commit**

```powershell
git add README.md docs/interview tests/test_interview_docs.py
git commit -m "docs: package the llm invoice review pilot"
```

---

## Deferred Enterprise-Hardening Plan

The following approved design items remain outside this LLM-focused delivery:

- multi-worker lease renewal and fencing tokens;
- atomic application transactions across Task, Run, Draft and Review Action changes;
- four-eyes approval and data-domain RBAC;
- malware scanning and storage integrity verification;
- MinIO TLS, encryption, lifecycle and legal-hold policy;
- centralized metrics, traces, alerts, capacity testing, HA and disaster recovery.

They should be presented as concrete production evolution, not as completed functionality.
