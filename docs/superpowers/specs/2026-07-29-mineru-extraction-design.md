# MinerU Production-Oriented Extraction Design

## 1. Purpose

Build a production-oriented document extraction pipeline for IVIDA Invoice and Receive Note reconciliation. The pilot will call MinerU Precision API rather than deploy MinerU locally, while preserving a Provider boundary that allows a later switch to self-hosted MinerU.

The pilot volume is fewer than 1,000 documents per month. Redacted customer documents may be sent to public APIs. Every extracted document must be reviewed and approved by a human before reconciliation.

## 2. Decisions

- Use MinerU Precision API as the only document parsing route in this phase.
- Use MinerU `vlm` mode with English document language and table parsing enabled.
- Use a separate text model to normalize MinerU output into the business JSON schema.
- Do not implement a direct visual-model comparison route in this phase.
- Do not deploy MinerU locally in this phase.
- Persist original files and large parsing artifacts in MinIO.
- Persist task state, searchable extraction data, normalized JSON, validation results, review versions and audit records in PostgreSQL.
- Require a human-approved immutable version before reconciliation.
- Keep deterministic calculation and validation outside all models.

## 3. Architecture

```text
Upload API
  -> MinIO original document
  -> PostgreSQL extraction task
  -> MinerUProvider (Precision API)
  -> MinIO MinerU artifacts
  -> NormalizationProvider (text model)
  -> PostgreSQL normalized draft
  -> ValidationService
  -> ReviewService
  -> immutable approved version
  -> ReconciliationService
```

Each component has one responsibility:

- `MinerUProvider`: submit, poll and download MinerU results; it has no Invoice business logic.
- `NormalizationProvider`: map MinerU content into the IVIDA document schema; it performs no financial calculations.
- `ValidationService`: calculate and validate fields deterministically.
- `ReviewService`: version drafts, enforce approval requirements and write audit records.
- `ReconciliationService`: accept approved versions only and calculate Invoice/Receive Note discrepancies.

## 4. Processing States

Primary state flow:

```text
uploaded
-> parsing
-> normalizing
-> validating
-> ready_for_review
-> approved
-> reconciled
```

Failure and review states:

```text
parsing_failed
normalization_failed
validation_failed
rejected
```

Every retry creates a new extraction run. A retry never overwrites a previous run, raw response or normalized output.

## 5. MinerU Provider

### 5.1 Request

The Provider reads the original object from MinIO and submits it to MinerU Precision API with:

- model: `vlm`
- language: English
- table parsing enabled
- request timeout: 10 minutes
- a stable internal submission key derived from the extraction run ID; the application prevents duplicate submission even if the external API has no idempotency header

The application stores the MinerU remote task ID immediately after submission.

### 5.2 Polling and retries

The Provider polls until MinerU reaches a terminal state. Transient network errors, HTTP 429 responses and MinerU 5xx responses receive at most three attempts with exponential backoff. An explicit MinerU parsing failure is recorded and is not automatically resubmitted as a new paid job.

### 5.3 Result contract

```python
@dataclass(frozen=True)
class ParseResult:
    provider: str
    model_name: str
    remote_task_id: str
    markdown: str
    content_blocks: list[dict]
    tables: list[dict]
    artifact_object_key: str
    page_count: int
    latency_ms: int
```

MinerU ZIP files, Markdown, images, table files and large intermediate JSON belong in MinIO. PostgreSQL stores their object keys, checksums and compact searchable summaries.

MinerU references:

- Official repository and deployment modes: <https://github.com/opendatalab/mineru>
- Official API ecosystem and Precision API: <https://github.com/opendatalab/MinerU-Ecosystem>

## 6. Normalization Provider

The initial Provider reuses the existing OpenAI-compatible text-model client pattern. It receives:

- expected document type
- MinerU Markdown
- table HTML or structured cells
- ordered content blocks
- the exact Invoice/Receive Note JSON Schema
- rules for Australian dates, AUD, GST-taxable and GST-free lines, and ABN formatting
- an instruction that missing data must be `null` and must never be invented

Configuration:

```text
temperature = 0
response format = JSON Schema
```

The model must not calculate, silently correct or infer financial values. It copies what the source presents. `ValidationService` owns all calculations.

The normalized response is validated with the existing Pydantic `Invoice` or `ReceiveNote` model. Invalid JSON gets one repair attempt using the validation errors. A second failure moves the run to `normalization_failed`.

## 7. Evidence

Critical fields and line items retain their source evidence:

```json
{
  "field": "purchase_order_number",
  "value": "PO-SYD-1042",
  "page": 1,
  "source_text": "Purchase Order PO-SYD-1042",
  "block_id": "block-17",
  "confidence": 0.98
}
```

Line evidence also records the source table ID, row index and original cells. Evidence is immutable for a given extraction run. Human edits create review-version changes without modifying extraction evidence.

## 8. Storage Model

### 8.1 MinIO

- original PDF or image
- MinerU result archive
- Markdown
- tables and images
- layout visualizations
- large raw responses

Objects are grouped by task and run:

```text
{document_type}/{task_id}/original/{filename}
{document_type}/{task_id}/runs/{run_id}/mineru/...
```

### 8.2 PostgreSQL

Existing:

- `extraction_tasks`
- `extraction_runs`

New logical entities:

- `parse_results`: MinerU task ID, summary, artifact keys and page count
- `document_drafts`: normalized JSON and current validation state
- `field_evidence`: source coordinates and text for fields and line items
- `validation_issues`: rule, severity, field path and measured difference
- `document_versions`: immutable human-edited versions
- `review_actions`: reviewer, action, timestamp and reason

JSONB stores flexible raw and normalized structures. Relational columns store status, ownership, timestamps, provider identity and fields used for filtering and uniqueness.

## 9. Deterministic Validation

Validation levels:

- `pass`
- `warning`
- `blocking`

Required checks:

- document type is Invoice or Receive Note
- document number is present
- currency is AUD
- dates parse successfully
- at least one line item exists
- quantity is positive
- unit price and amounts are non-negative
- `line_total` is consistent with `quantity * unit_price`
- subtotal equals the sum of line totals
- GST is consistent with printed tax codes: 10% for GST-taxable lines and zero for GST-free lines
- total equals subtotal plus GST
- duplicate file and document-number candidates are identified

Default tolerances:

- line amount: AUD 0.02
- document total: AUD 0.05

Blocking examples:

- missing document number
- all line items missing
- unreadable total
- schema-invalid normalized output
- document-type conflict
- evidence suggests a missing table row

Warning examples:

- malformed ABN format
- missing PO number
- missing SKU
- small GST difference
- low-confidence field
- suspected duplicate

## 10. Human Review

Every successful extraction reaches `ready_for_review`; no confidence threshold bypasses review.

The review UI must show:

- original PDF
- MinerU Markdown and tables
- normalized fields
- field and line evidence
- validation issues
- model and run metadata
- version history

Reviewer actions:

- edit fields
- add, edit or remove line items
- mark a value as unable to confirm
- save draft
- approve
- reject with a reason

Approval requires:

- no unresolved blocking issue
- all required fields present
- an authenticated reviewer
- creation of a new immutable approved version

Roles:

- `Reviewer`: view, edit, approve and reject
- `Admin`: Reviewer permissions plus Provider configuration, task retry and account management

Every mutation records reviewer identity, timestamp, old value, new value and reason.

## 11. Reconciliation Gate

`ReconciliationService` receives approved version IDs, not mutable task drafts or raw model output. It rejects any version that is not approved.

This gate prevents:

- automatic model output from becoming a financial result
- a later draft edit from changing an existing reconciliation
- an extraction retry from silently replacing reviewed data

## 12. Error Handling

Automatically retry:

- connection timeout
- HTTP 429
- MinerU 5xx
- temporary artifact-download failure

Do not automatically loop:

- corrupted file
- unsupported document
- explicit MinerU parse failure
- repeated invalid normalized JSON
- unreadable source

Errors are categorized with stable codes and safe messages. Logs and API responses never include MinerU tokens, model API keys, database credentials or original document content.

## 13. Security

- Replace the MinerU token disclosed in chat before implementation testing.
- Store the replacement only as `MINERU_API_TOKEN` in the ignored `.env`.
- Redact real documents before public API submission.
- Limit PostgreSQL 5432 at the cloud security group to approved client IPs.
- Keep original and extracted artifacts private in MinIO.
- Record who exported, approved or rejected a document.
- Never place secrets in task payloads, logs, PostgreSQL JSONB or MinIO object names.

## 14. Pilot Acceptance

Against the current synthetic Australian pizza procurement set:

- all 17 PDFs reach a terminal extraction state without manual technical intervention
- all critical header fields are exact on the clean synthetic set
- line-item precision and recall are at least 95%
- amount, GST and quantity results fall inside configured tolerance
- invalid normalized JSON can never reach approval
- single-page extraction P95 is no more than 120 seconds
- every call records provider, model, latency and cost metadata
- every reconciled document references an immutable approved version

The same evaluation tooling must later accept redacted real samples without committing them to Git.

## 15. Testing

- unit tests for Provider request mapping, response parsing and error classification
- contract tests using recorded redacted MinerU responses
- schema tests for normalization and repair
- rule tests for GST, totals, line arithmetic and missing fields
- repository tests for drafts, versions, evidence and audit rows
- API tests for queueing, retry, review, approval and reconciliation gates
- integration tests against MinerU sandbox/Precision API using ignored synthetic files
- full evaluation run over all 17 PDFs with a machine-readable metrics report

Integration tests that call paid APIs are opt-in and never run in the default unit-test command.

## 16. Out of Scope

- local MinerU deployment
- direct visual-model extraction route
- automatic approval
- production billing integration
- supplier-specific parsing templates
- mobile review UI
- multi-tenant customer isolation
