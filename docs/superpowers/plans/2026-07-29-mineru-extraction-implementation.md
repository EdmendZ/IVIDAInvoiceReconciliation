# MinerU Extraction and Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse uploaded Invoice and Receive Note files through MinerU Precision API, normalize them into the existing business schema, validate them deterministically, and place successful drafts in `ready_for_review`.

**Architecture:** Replace the current one-step `ExtractionProvider` with an asynchronous MinerU parser, a separate text normalization Provider, a PostgreSQL-backed worker queue, and deterministic validation. MinerU artifacts remain in MinIO; PostgreSQL stores run state, parse summaries, normalized drafts, evidence, issues, usage and cost.

**Tech Stack:** Python 3.11, FastAPI, PostgreSQL 18, SQLAlchemy 2, Alembic, MinIO, `mineru-open-sdk`, OpenAI-compatible text API, Pydantic 2, pytest.

## Global Constraints

- Project root is `E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation`.
- MinerU mode is `vlm`, language is `en`, OCR and table parsing are enabled.
- The MinerU token disclosed in chat must be rotated; only the replacement may be placed in ignored `.env`.
- No API key or document content may appear in logs, exceptions or committed fixtures.
- Original files and large MinerU artifacts stay in MinIO.
- PostgreSQL remains the source of truth for task and run state.
- All external calls use explicit timeouts and stable error codes.
- Paid MinerU integration tests are opt-in.
- No document may skip `ready_for_review` or become approved in this plan.

---

### Task 1: Split parsing and normalization contracts

**Files:**
- Create: `app/domain/parsing.py`
- Create: `app/domain/normalization.py`
- Modify: `app/services/extraction_provider.py`
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Modify: `pyproject.toml`
- Test: `tests/test_provider_contracts.py`

**Interfaces:**
- Produces: `AsyncDocumentParser.submit()`, `AsyncDocumentParser.poll()`, `NormalizationProvider.normalize()`.
- Produces: `ParserSubmission`, `ParserPollResult`, `ParseResult`, `NormalizationResult`, `FieldEvidence`.
- Consumes: existing `BusinessDocument` and `DocumentType`.

- [ ] **Step 1: Write failing contract and secret-redaction tests**

```python
from app.core.config import Settings
from app.domain.parsing import ParseState, ParserSubmission


def test_mineru_token_is_not_in_settings_repr() -> None:
    settings = Settings(mineru_api_token="secret-value")
    assert "secret-value" not in repr(settings)


def test_parser_submission_has_stable_remote_id() -> None:
    submission = ParserSubmission(remote_job_id="batch-1")
    assert submission.remote_job_id == "batch-1"
    assert ParseState.QUEUED.value == "queued"
```

- [ ] **Step 2: Run the new test and verify import failure**

Run:

```powershell
uv run pytest tests\test_provider_contracts.py -q
```

Expected: FAIL because `app.domain.parsing` does not exist.

- [ ] **Step 3: Add dependencies and configuration**

Add runtime dependencies:

```toml
"mineru-open-sdk>=1,<2",
"openai>=1.100,<3",
```

Add settings:

```python
mineru_api_token: str = Field(default="", repr=False)
mineru_base_url: str = "https://mineru.net/api/v4"
mineru_model: str = "vlm"
mineru_language: str = "en"
mineru_timeout_seconds: int = 600
mineru_poll_interval_seconds: int = 5
normalization_base_url: str = ""
normalization_api_key: str = Field(default="", repr=False)
normalization_model: str = ""
normalization_timeout_seconds: int = 120
```

Add the same names to `.env.example` with `CHANGE_ME` values and no real token.

- [ ] **Step 4: Define exact parser domain types**

```python
class ParseState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ParserSubmission(BaseModel):
    remote_job_id: str


class ParseResult(BaseModel):
    provider: str
    model_name: str
    remote_task_id: str | None
    markdown: str
    content_blocks: list[dict]
    tables: list[dict]
    page_count: int
    artifact_archive: bytes = Field(exclude=True)


class ParserPollResult(BaseModel):
    state: ParseState
    progress: int = Field(ge=0, le=100)
    result: ParseResult | None = None
    error_code: str | None = None
    error_message: str | None = None
```

Define:

```python
class AsyncDocumentParser(Protocol):
    provider_name: str
    model_name: str

    def submit(
        self, *, filename: str, content_type: str, content: bytes
    ) -> ParserSubmission:
        raise NotImplementedError

    def poll(self, remote_job_id: str) -> ParserPollResult:
        raise NotImplementedError
```

- [ ] **Step 5: Define normalization and evidence types**

```python
class FieldEvidence(BaseModel):
    field_path: str
    value: str | None
    page: int | None
    source_text: str
    block_id: str | None
    table_id: str | None = None
    row_index: int | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)


class NormalizationResult(BaseModel):
    document: BusinessDocument
    evidence: list[FieldEvidence]
    raw_response: dict
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_aud: Decimal | None = None


class NormalizationProvider(Protocol):
    provider_name: str
    model_name: str

    def normalize(
        self, *, document_type: DocumentType, parse_result: ParseResult
    ) -> NormalizationResult:
        raise NotImplementedError
```

- [ ] **Step 6: Run tests and the current suite**

```powershell
uv sync
uv run pytest tests\test_provider_contracts.py -q
uv run pytest -q
```

Expected: contract test PASS and existing suite PASS.

- [ ] **Step 7: Commit**

```powershell
git add .env.example pyproject.toml uv.lock app/domain app/services/extraction_provider.py app/core/config.py tests/test_provider_contracts.py
git commit -m "refactor: split parsing and normalization contracts"
```

---

### Task 2: Implement the MinerU Precision API adapter

**Files:**
- Create: `app/infra/mineru_parser.py`
- Create: `app/infra/external_errors.py`
- Test: `tests/test_mineru_parser.py`
- Test fixture: `tests/fixtures/mineru/done_result.json`

**Interfaces:**
- Consumes: `AsyncDocumentParser`, `ParserSubmission`, `ParserPollResult`.
- Produces: `MinerUPrecisionParser.submit()` and `MinerUPrecisionParser.poll()`.
- Uses official SDK flow `submit(path) -> batch_id -> get_batch(batch_id)[0]`.

- [ ] **Step 1: Write failing submit and poll tests with a fake SDK**

```python
class FakeMinerUClient:
    def submit(self, path: str, **options) -> str:
        self.path = path
        self.options = options
        return "batch-123"

    def get_batch(self, batch_id: str):
        return [FakeDoneResult()]


def test_submit_uses_vlm_english_ocr_and_tables(tmp_path) -> None:
    client = FakeMinerUClient()
    parser = MinerUPrecisionParser(client=client, timeout_seconds=600)
    result = parser.submit(
        filename="invoice.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7",
    )
    assert result.remote_job_id == "batch-123"
    assert client.options == {
        "model": "vlm",
        "ocr": True,
        "table": True,
        "formula": False,
        "language": "en",
    }


def test_poll_maps_done_result_to_parse_result() -> None:
    parser = MinerUPrecisionParser(client=FakeMinerUClient(), timeout_seconds=600)
    result = parser.poll("batch-123")
    assert result.state == ParseState.SUCCEEDED
    assert result.result.markdown == "# TAX INVOICE"
```

- [ ] **Step 2: Run tests and verify failure**

```powershell
uv run pytest tests\test_mineru_parser.py -q
```

Expected: FAIL because `MinerUPrecisionParser` is missing.

- [ ] **Step 3: Add safe external error types**

```python
class ExternalServiceError(RuntimeError):
    def __init__(self, code: str, safe_message: str, retryable: bool) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
```

Map timeout, 429 and 5xx to retryable codes. Map explicit parse failure, unsupported file and authentication failure to non-retryable codes. Never include SDK request headers or token text.

- [ ] **Step 4: Implement secure temporary-file submission**

Use `NamedTemporaryFile(delete=False, suffix=Path(filename).suffix)`; close before SDK upload on Windows and delete it in `finally`.

```python
batch_id = self._client.submit(
    temporary_path,
    model="vlm",
    ocr=True,
    table=True,
    formula=False,
    language="en",
)
return ParserSubmission(remote_job_id=batch_id)
```

- [ ] **Step 5: Implement polling and artifact packaging**

Map SDK states:

```python
if sdk_result.state == "done":
    return ParserPollResult(
        state=ParseState.SUCCEEDED,
        progress=100,
        result=self._build_result(sdk_result),
    )
if sdk_result.state == "failed":
    return ParserPollResult(
        state=ParseState.FAILED,
        progress=sdk_result.progress or 0,
        error_code="MINERU_PARSE_FAILED",
        error_message="MinerU could not parse the document",
    )
return ParserPollResult(
    state=ParseState.RUNNING,
    progress=sdk_result.progress or 0,
)
```

Create a ZIP in memory containing `document.md`, `content_list.json`, extracted images and a sanitized `manifest.json`. Do not store SDK debug logs.

- [ ] **Step 6: Run tests**

```powershell
uv run pytest tests\test_mineru_parser.py -q
uv run pytest -q
```

Expected: all PASS without calling the live API.

- [ ] **Step 7: Commit**

```powershell
git add app/infra/mineru_parser.py app/infra/external_errors.py tests/test_mineru_parser.py tests/fixtures/mineru
git commit -m "feat: add MinerU precision parser"
```

---

### Task 3: Add durable parse state and result persistence

**Files:**
- Modify: `app/domain/extraction_runs.py`
- Create: `app/domain/parse_results.py`
- Modify: `app/infra/database_models.py`
- Create: `app/infra/postgres_parse_repository.py`
- Modify: `app/services/ports.py`
- Create: `migrations/versions/20260729_03_add_parse_results_and_leases.py`
- Test: `tests/test_postgres_parse_repository.py`

**Interfaces:**
- Produces: `ExtractionRunRepository.claim_next()`, `set_remote_job()`, `schedule_poll()`.
- Produces: `ParseResultRepository.create()`, `get_for_run()`.
- Consumes: existing extraction tasks/runs and MinIO artifact object keys.

- [ ] **Step 1: Write failing PostgreSQL-adapter tests using SQLite**

```python
def test_claim_next_returns_oldest_queued_run(repository, queued_runs) -> None:
    claimed = repository.claim_next(
        worker_id="worker-1",
        lease_seconds=60,
        now=datetime(2026, 7, 29, tzinfo=UTC),
    )
    assert claimed.run_id == queued_runs[0].run_id
    assert claimed.lease_owner == "worker-1"


def test_parse_result_round_trip(parse_repository, run) -> None:
    parse_repository.create(
        ParseResultRecord(
            parse_result_id=str(uuid4()),
            run_id=run.run_id,
            remote_job_id="batch-123",
            artifact_object_key="invoice/task/runs/run/mineru/result.zip",
            markdown="# TAX INVOICE",
            content_blocks=[{"block_id": "1"}],
            tables=[],
            page_count=1,
            created_at=datetime.now(UTC),
        )
    )
    assert parse_repository.get_for_run(run.run_id).page_count == 1
```

- [ ] **Step 2: Run and verify failure**

```powershell
uv run pytest tests\test_postgres_parse_repository.py -q
```

- [ ] **Step 3: Extend run state**

Add:

```python
class ExtractionRunStatus(StrEnum):
    QUEUED = "queued"
    SUBMITTING = "submitting"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    VALIDATING = "validating"
    READY_FOR_REVIEW = "ready_for_review"
    FAILED = "failed"
```

Add run fields `remote_job_id`, `attempt_count`, `next_attempt_at`, `lease_owner`, `lease_expires_at`, and `phase_error_code`.

- [ ] **Step 4: Add migration**

Create `parse_results` with:

- UUID-string primary key
- unique `run_id` foreign key with cascade delete
- MinerU remote job ID
- MinIO artifact key
- Markdown text
- JSONB content blocks and tables
- page count
- created timestamp

Add an index on `(status, next_attempt_at, created_at)` to `extraction_runs`.

- [ ] **Step 5: Implement atomic claiming**

For PostgreSQL use:

```sql
SELECT run_id
FROM extraction_runs
WHERE status IN ('queued', 'parsing', 'normalizing', 'validating')
  AND next_attempt_at <= :now
  AND (lease_expires_at IS NULL OR lease_expires_at < :now)
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1
```

Update the claimed row in the same transaction. Keep a repository fallback suitable for SQLite tests without `SKIP LOCKED`.

- [ ] **Step 6: Run migration SQL and tests**

```powershell
uv run alembic upgrade head --sql
uv run pytest tests\test_postgres_parse_repository.py -q
uv run pytest -q
```

- [ ] **Step 7: Commit**

```powershell
git add app/domain app/infra app/services/ports.py migrations/versions/20260729_03_add_parse_results_and_leases.py tests/test_postgres_parse_repository.py
git commit -m "feat: persist MinerU parse results and worker leases"
```

---

### Task 4: Replace FastAPI BackgroundTasks with a durable worker

**Files:**
- Modify: `app/services/extraction_service.py`
- Modify: `app/api/extraction_routes.py`
- Modify: `app/api/dependencies.py`
- Create: `app/workers/__init__.py`
- Create: `app/workers/extraction_worker.py`
- Create: `run_extraction_worker.py`
- Test: `tests/test_extraction_worker.py`
- Modify: `tests/test_extraction_api.py`

**Interfaces:**
- Produces: `ExtractionWorker.run_once(worker_id: str) -> bool`.
- Queue endpoint creates a `queued` run and returns HTTP 202; it performs no paid API call.
- Consumes: MinerU parser, MinIO, task/run/parse repositories.

- [ ] **Step 1: Write failing durable-queue tests**

```python
def test_queue_does_not_call_parser(extraction_service, parser) -> None:
    run = extraction_service.queue(task_id)
    assert run.status == ExtractionRunStatus.QUEUED
    parser.submit.assert_not_called()


def test_worker_submits_then_polls_until_done(worker, parser, repositories) -> None:
    parser.submit.return_value = ParserSubmission(remote_job_id="batch-123")
    parser.poll.return_value = succeeded_poll_result()
    assert worker.run_once("worker-1") is True
    saved = repositories.parse_results.get_for_run(run_id)
    assert saved.remote_job_id == "batch-123"
```

- [ ] **Step 2: Run tests and verify failure**

```powershell
uv run pytest tests\test_extraction_worker.py tests\test_extraction_api.py -q
```

- [ ] **Step 3: Make queue durable**

Refactor `ExtractionService.queue()` to create a `queued` run and set the task to `extracting`. Remove `BackgroundTasks` from `start_extraction`.

```python
@router.post(
    "/extraction-tasks/{task_id}/extract",
    response_model=ExtractionRun,
    status_code=202,
)
def start_extraction(
    task_id: str,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionRun:
    return service.queue(task_id)
```

- [ ] **Step 4: Implement worker phases**

`run_once()`:

1. claim one run
2. if queued/submitting: read MinIO object and submit MinerU
3. persist remote batch ID before returning
4. if parsing: poll MinerU
5. when running: schedule the next poll
6. when done: save ZIP to `{document_type}/{task_id}/runs/{run_id}/mineru/result.zip`
7. create `parse_results`
8. move run to `normalizing`
9. release the lease

Transient failures increment `attempt_count` and calculate `next_attempt_at = now + min(60, 2 ** attempt_count)` seconds. A fourth transient failure marks the run failed.

- [ ] **Step 5: Add worker entry point**

```python
if __name__ == "__main__":
    worker = build_extraction_worker()
    worker.run_forever(
        worker_id=f"{socket.gethostname()}-{os.getpid()}",
        idle_seconds=2,
    )
```

The worker catches errors per run, logs only task/run IDs and continues.

- [ ] **Step 6: Run tests**

```powershell
uv run pytest tests\test_extraction_worker.py tests\test_extraction_api.py -q
uv run pytest -q
```

- [ ] **Step 7: Commit**

```powershell
git add app/services/extraction_service.py app/api app/workers run_extraction_worker.py tests
git commit -m "feat: add durable extraction worker"
```

---

### Task 5: Implement OpenAI-compatible normalization

**Files:**
- Create: `app/infra/openai_normalization_provider.py`
- Create: `app/resources/prompts/normalize_document_system.txt`
- Create: `app/resources/prompts/normalize_document_user.txt`
- Modify: `app/api/dependencies.py`
- Test: `tests/test_normalization_provider.py`
- Fixture: `tests/fixtures/normalization/invoice_response.json`

**Interfaces:**
- Consumes: `ParseResult`, `DocumentType`.
- Produces: `NormalizationResult` containing a validated business document and evidence.

- [ ] **Step 1: Write failing structured-output tests**

```python
def test_invoice_response_becomes_valid_document(fake_openai_client) -> None:
    provider = OpenAINormalizationProvider(
        client=fake_openai_client,
        model_name="normalizer-test",
    )
    result = provider.normalize(
        document_type=DocumentType.INVOICE,
        parse_result=invoice_parse_result(),
    )
    assert result.document.document_number == "SCF-INV-260701"
    assert result.evidence[0].field_path == "document_number"


def test_missing_value_is_null_not_empty_string(fake_openai_client) -> None:
    fake_openai_client.response = response_with_empty_po()
    with pytest.raises(NormalizationSchemaError):
        provider.normalize(
            document_type=DocumentType.INVOICE,
            parse_result=invoice_parse_result(),
        )
```

- [ ] **Step 2: Run and verify failure**

```powershell
uv run pytest tests\test_normalization_provider.py -q
```

- [ ] **Step 3: Write the system prompt**

The prompt must state:

- copy source values; never invent
- use `null` for missing values
- do not calculate or correct totals
- preserve printed tax codes
- emit line evidence with page, block and table row
- return only the supplied JSON Schema

Include the complete Pydantic-generated schema in the request rather than maintaining a second handwritten schema.

- [ ] **Step 4: Implement the Provider**

Use an injected OpenAI-compatible client:

```python
response = self._client.chat.completions.create(
    model=self._model_name,
    temperature=0,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    timeout=self._timeout_seconds,
)
```

Validate the response against a `NormalizedDocumentEnvelope` containing `document` and `evidence`. Reject empty strings for nullable identifier fields. On schema failure, make one repair call that includes only validation errors and the previous response, not the original PDF.

- [ ] **Step 5: Record usage safely**

Copy input/output tokens from response usage. Calculate estimated AUD cost only when per-million-token rates are configured; otherwise leave it `null`. Never log message contents.

- [ ] **Step 6: Run tests**

```powershell
uv run pytest tests\test_normalization_provider.py -q
uv run pytest -q
```

- [ ] **Step 7: Commit**

```powershell
git add app/infra/openai_normalization_provider.py app/resources/prompts app/api/dependencies.py tests/test_normalization_provider.py tests/fixtures/normalization
git commit -m "feat: normalize MinerU output into business documents"
```

---

### Task 6: Persist drafts, evidence and validation issues

**Files:**
- Create: `app/domain/document_drafts.py`
- Create: `app/domain/validation.py`
- Modify: `app/infra/database_models.py`
- Create: `app/infra/postgres_draft_repository.py`
- Create: `app/services/validation_service.py`
- Modify: `app/workers/extraction_worker.py`
- Create: `migrations/versions/20260729_04_add_drafts_evidence_and_issues.py`
- Test: `tests/test_validation_service.py`
- Test: `tests/test_postgres_draft_repository.py`

**Interfaces:**
- Produces: `ValidationService.validate(document) -> ValidationReport`.
- Produces: `DocumentDraftRepository.create_with_evidence_and_issues(draft, evidence, issues) -> DocumentDraft`.
- A successful worker run ends at `ready_for_review`; it never approves.

- [ ] **Step 1: Write failing GST and arithmetic tests**

```python
def test_taxable_and_gst_free_lines_are_validated_separately() -> None:
    report = service.validate(document_with_taxable_and_gst_free_lines())
    assert report.blocking_count == 0


def test_wrong_total_is_blocking() -> None:
    report = service.validate(invoice(total="110.00", subtotal="90.00", tax="9.00"))
    issue = next(item for item in report.issues if item.rule_code == "TOTAL_MISMATCH")
    assert issue.severity == IssueSeverity.BLOCKING


def test_missing_po_is_warning() -> None:
    report = service.validate(invoice(purchase_order_number=None))
    assert report.has_warning("PO_MISSING")
```

- [ ] **Step 2: Run and verify failure**

```powershell
uv run pytest tests\test_validation_service.py -q
```

- [ ] **Step 3: Add validation types and exact tolerances**

```python
class IssueSeverity(StrEnum):
    WARNING = "warning"
    BLOCKING = "blocking"


class ValidationIssue(BaseModel):
    rule_code: str
    severity: IssueSeverity
    field_path: str
    message: str
    measured_difference: Decimal | None = None


class ValidationReport(BaseModel):
    issues: list[ValidationIssue]
    line_tolerance: Decimal = Decimal("0.02")
    document_tolerance: Decimal = Decimal("0.05")
```

- [ ] **Step 4: Implement deterministic rules**

Implement named functions for required identifiers, positive quantity, non-negative money, line arithmetic, subtotal, tax by printed tax code, total, duplicate candidates and evidence completeness. Each function returns zero or more `ValidationIssue` values and has a focused unit test.

- [ ] **Step 5: Add database migration**

Create:

- `document_drafts(run_id unique, task_id, document_type, normalized_json JSONB, validation_state, created_at, updated_at)`
- `field_evidence(draft_id, field_path, value, page, source_text, block_id, table_id, row_index, confidence)`
- `validation_issues(draft_id, rule_code, severity, field_path, message, measured_difference, resolved_at)`

Index draft task ID, unresolved issue severity and evidence draft/field path.

- [ ] **Step 6: Complete the worker**

After parsing:

1. load persisted parse result
2. call normalization Provider
3. validate the Pydantic document
4. run deterministic validation
5. persist draft, evidence and issues in one transaction
6. set run and task to `ready_for_review`

Any exception before the transaction commits leaves no partial draft and moves the run to a phase-specific failed state.

- [ ] **Step 7: Run migration and tests**

```powershell
uv run alembic upgrade head --sql
uv run pytest tests\test_validation_service.py tests\test_postgres_draft_repository.py -q
uv run pytest -q
```

- [ ] **Step 8: Commit**

```powershell
git add app/domain app/infra app/services/validation_service.py app/workers migrations/versions/20260729_04_add_drafts_evidence_and_issues.py tests
git commit -m "feat: persist validated extraction drafts"
```

---

### Task 7: Add extraction result APIs and evaluation runner

**Files:**
- Modify: `app/api/extraction_routes.py`
- Create: `app/api/schemas/extraction.py`
- Create: `tools/run_mineru_evaluation.py`
- Create: `tools/score_extraction_results.py`
- Modify: `docs/evaluation-dataset.md`
- Modify: `README.md`
- Test: `tests/test_extraction_result_api.py`
- Test: `tests/test_evaluation_scoring.py`

**Interfaces:**
- Produces: `GET /api/extraction-runs/{run_id}/result`.
- Produces: ignored `evaluation_data/results/{evaluation_run_id}/metrics.json`.
- Consumes: current 17-PDF manifest and gold JSON.

- [ ] **Step 1: Write failing result API test**

```python
def test_result_api_returns_draft_evidence_and_issues(client, ready_run) -> None:
    response = client.get(f"/api/extraction-runs/{ready_run.run_id}/result")
    assert response.status_code == 200
    body = response.json()
    assert body["draft"]["document_number"] == "SCF-INV-260701"
    assert body["evidence"][0]["field_path"] == "document_number"
    assert body["approval_allowed"] is False
```

- [ ] **Step 2: Write failing scoring tests**

```python
def test_line_item_metrics_are_order_independent() -> None:
    score = score_document(predicted_lines_reversed(), gold_document())
    assert score.line_precision == Decimal("1")
    assert score.line_recall == Decimal("1")


def test_wrong_po_reduces_critical_header_accuracy() -> None:
    score = score_document(predicted_with_wrong_po(), gold_document())
    assert score.critical_headers_correct == 3
    assert score.critical_headers_total == 4
```

- [ ] **Step 3: Implement the result API**

Return task/run metadata, parse artifact key, normalized draft, evidence, validation issues and usage/cost. Never return secrets, raw request headers or internal exception traces.

- [ ] **Step 4: Implement opt-in evaluation**

`run_mineru_evaluation.py` must refuse to run unless:

```text
RUN_PAID_INTEGRATION_TESTS=true
MINERU_API_TOKEN is non-empty
```

For each manifest document:

1. upload through existing service
2. queue extraction
3. run worker until terminal
4. save the result under ignored `evaluation_data/results`
5. retain failed results for diagnosis

Do not automatically delete evaluation results; add a separate `--cleanup` flag that deletes only task IDs listed in that run's own manifest.

- [ ] **Step 5: Implement metrics**

Report:

- document terminal success count
- critical header exact accuracy
- line-item precision and recall matched by SKU, then normalized description
- quantity, unit price, subtotal, GST and total accuracy
- P50/P95 latency
- input/output tokens
- recorded or estimated AUD cost
- validation warning/blocking counts

- [ ] **Step 6: Run local tests**

```powershell
uv run pytest tests\test_extraction_result_api.py tests\test_evaluation_scoring.py -q
uv run python tools\validate_evaluation_dataset.py
uv run pytest -q
```

- [ ] **Step 7: Rotate and configure the MinerU token**

Revoke the token disclosed in chat. Set the replacement value for `MINERU_API_TOKEN` only in the ignored `.env`; do not put the replacement value in this plan or a command transcript. Confirm the non-secret model settings are:

```dotenv
MINERU_MODEL=vlm
MINERU_LANGUAGE=en
```

Confirm:

```powershell
git check-ignore .env
git grep -n "sk-" -- . ':!uv.lock'
```

Expected: `.env` is ignored and `git grep` returns no secret.

- [ ] **Step 8: Apply the real migration and run the paid evaluation once**

```powershell
uv run python init_database.py
$env:RUN_PAID_INTEGRATION_TESTS="true"
uv run python tools\run_mineru_evaluation.py
uv run python tools\score_extraction_results.py
```

Expected: migration head is `20260729_04`; a metrics JSON exists; no document is approved.

- [ ] **Step 9: Commit**

```powershell
git add app/api tools docs/evaluation-dataset.md README.md tests
git commit -m "feat: evaluate MinerU extraction results"
```

## Phase A Completion Gate

Before starting the review plan:

```powershell
uv run pytest -q
uv run python tools\validate_evaluation_dataset.py
uv run alembic current
git status --short
```

Require:

- all unit and API tests pass
- 8 cases and 17 PDFs validate
- database migration is `20260729_04`
- real MinerU evaluation has a terminal result for all 17 PDFs
- no secret is tracked
- no run is approved
