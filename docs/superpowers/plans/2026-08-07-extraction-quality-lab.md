# Extraction Quality Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a versioned, auditable extraction experiment workflow that compares baseline and candidate model configurations, explains regressions, and turns confirmed reviewer corrections into governed evaluation feedback.

**Architecture:** Keep `app/evaluation` responsible for document prediction and raw metrics. Add `app/experiments` for immutable experiment definitions, persisted runs, error slicing, feedback governance, and promotion decisions. Real model experiments run from a CLI and persist results; an admin-only API and React page read and govern results without placing long model calls inside FastAPI requests.

**Tech Stack:** Python 3.11–3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL/JSONB, pytest, React 19, TypeScript, Vitest, MinerU, and the existing OpenAI-compatible provider.

## Global Constraints

- Never automatically modify `.env`, default model, Prompt files, deployment configuration, or release configuration.
- Only an explicitly confirmed `model_error` feedback candidate may become eligible for a later Gold dataset version.
- Baseline and candidate comparisons require identical dataset version, manifest SHA-256, and document SHA-256 set.
- Failed documents remain in the denominator.
- Unknown cost remains `None`/`unknown`, never numeric zero.
- Promotion fails closed: incomplete evidence or internal errors produce `inconclusive`, never `recommended`.
- Real MinerU/model calls run from the CLI, not a FastAPI request.
- Experiment and feedback mutations require `require_admin`.
- Do not mix unrelated refactors of Case, review, or ORM files into this feature.
- Update mapped evaluation, review, API, database, operations, and interview documents.

---

## File Map

**Create:** `app/experiments/{__init__,domain,ports,slicing,promotion,runner,feedback,reporting}.py`, `app/infra/postgres_experiment_repository.py`, `app/api/experiment_routes.py`, `app/cli/create_experiment.py`, `app/cli/run_experiment.py`, `migrations/versions/20260807_12_add_extraction_quality_lab.py`.

**Create frontend:** `frontend/src/experiments/{experimentTypes,experimentPresentation,experimentPresentation.test,ExperimentLabPage,ExperimentLabPage.test}.ts[x]`.

**Modify:** `app/infra/database_models.py`, `app/api/dependencies.py`, `app/main.py`, `app/evaluation/runner.py`, `app/cli/evaluate_extraction.py`, `app/infra/postgres_review_repository.py`, `tests/fakes.py`, `frontend/src/app/App.tsx`, `frontend/src/styles.css`, and mapped documentation.

Tasks 1–4 form Milestone 1: a usable persisted CLI experiment and fail-closed decision core. Tasks 5–7 form Milestone 2: governed human feedback plus the admin API/UI. Task 8 validates the combined interview workflow. Review and merge each milestone independently if implementation risk or PR size requires a split.

## Recommended PR and Stop/Go Plan

### PR A — Pure quality logic

Includes Tasks 1–2 only: immutable contracts, business/error slicing, and fail-closed Promotion rules. It has no database, API, UI, or external model calls. Merge only when every hard-gate branch has a focused unit test.

**Go condition:** slice counts include failed documents, business scenarios, field groups, and Evidence gaps; Promotion returns all three outcomes with explicit reasons.

### PR B — Persisted CLI experiment MVP

Includes Tasks 3–4: migration, repository, definition-creation CLI, real-run CLI, dataset identity, persisted progress, cancellation, and safe reporting. This is the **minimum interview-ready stopping point**. It can demonstrate reproducible model comparison from the terminal without committing to a new admin product surface.

**Go condition:** one live-document smoke succeeds or persists a safe diagnostic failure; two saved 17-document runs can be compared without rerunning MinerU; migration upgrade/downgrade succeeds.

**Stop condition:** if the 17-document evidence does not expose meaningful model/Prompt differences, pause before building UI. Improve the dataset and error slices first; a dashboard around inconclusive evidence has low interview value.

### PR C — Governed human feedback

Includes Tasks 5–6: Feedback Candidate extraction, immutable classification, admin API, and server-side Gold eligibility. This PR is independently valuable only after PR B produces stable model provenance.

**Go condition:** a real Reviewer edit can be traced to Draft, Run, model, Prompt, old value, and new value; non-model-error feedback cannot enter Gold through either service or API.

### PR D — Interview console and packaging

Includes Tasks 7–8: text-first Lab page, documentation, full regression verification, and the 5–8 minute demo. Do not begin this PR until baseline/candidate data and at least one confirmed Feedback Candidate exist.

**Go condition:** the demo explains one improvement, one remaining regression, cost/latency trade-offs, and why recommendation does not deploy automatically.

## Scope Reduction Order

If time becomes limited, cut scope in this order:

1. Remove frontend creation forms; keep the Lab read-only and use CLIs for definitions/runs.
2. Remove automatic Feedback backfill; collect only newly selected review versions.
3. Omit persisted Markdown reports; retain structured JSON and deterministic rendering on demand.
4. Keep only document type, field group, error type, and business scenario slices.

Never cut dataset identity, failure-in-denominator behavior, critical-field gates, feedback confirmation, or the distinction between recommendation and deployment. Those are the capabilities that make the feature credible in an LLM application interview.

---

### Task 1: Domain Contracts and Error Slicing

**Files:**
- Create: `app/experiments/__init__.py`
- Create: `app/experiments/domain.py`
- Create: `app/experiments/slicing.py`
- Modify: `app/evaluation/models.py`
- Test: `tests/test_experiment_slicing.py`

**Interfaces:**
- Consumes: `DocumentEvaluation`, `EvaluationSummary`.
- Produces: `DatasetIdentity`, `ExperimentThresholds`, `ExperimentDefinition`, `EvaluationRun`, `ErrorSlice`, `FeedbackCandidate`, `PromotionCheck`, `PromotionDecision`; `build_error_slices(documents: list[DocumentEvaluation]) -> list[ErrorSlice]`. Extend `DocumentEvaluation` with `business_scenario: str` populated from manifest `expected_outcome`.

- [ ] **Step 1: Write the failing slice test**

```python
def test_slices_keep_failures_and_purchase_errors(document_evaluations):
    slices = build_error_slices(document_evaluations)
    indexed = {(item.dimension, item.value): item for item in slices}
    assert indexed[("error_type", "schema_failure")].document_count == 1
    assert indexed[("field_group", "purchase")].error_count == 1
    assert indexed[("document_type", "invoice")].document_count == 2
    assert indexed[("business_scenario", "purchase_order_conflict")].document_count == 2
```

The fixture contains one Schema failure and one valid invoice with a `purchase_order_number` mismatch.

- [ ] **Step 2: Verify the test fails**

Run: `uv run pytest tests/test_experiment_slicing.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.experiments'`.

- [ ] **Step 3: Add exact enums and frozen definitions**

```python
class ExperimentRole(StrEnum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"

class EvaluationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class FeedbackClassification(StrEnum):
    MODEL_ERROR = "model_error"
    ACCEPTABLE_VARIANT = "acceptable_variant"
    REVIEWER_CORRECTION_ERROR = "reviewer_correction_error"
    BUSINESS_CONTEXT_UPDATE = "business_context_update"

class PromotionOutcome(StrEnum):
    RECOMMENDED = "recommended"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
```

Use `ConfigDict(frozen=True)` for `DatasetIdentity`, `ExperimentThresholds`, and `ExperimentDefinition`. Dataset identity contains version, manifest hash, and sorted document hashes. Run contains optional summary, all document results, slices, and safe error fields.

`ExperimentDefinition` fields are exactly: `experiment_id`, `name`, `role`, `manifest_path`, `dataset_identity`, `parser_provider`, `parser_model`, `parser_version`, `normalizer_provider`, `normalizer_model`, `prompt_version`, `schema_version`, `parameters: dict[str, object]`, `thresholds`, `created_by`, and `created_at`. `ExperimentThresholds` fields are `required_schema_valid_rate`, `minimum_field_accuracy`, `minimum_line_item_f1`, `minimum_evidence_coverage`, `max_cost_aud_per_document`, `require_known_cost`, `critical_field_paths`, and `target_slices`.

- [ ] **Step 4: Implement deterministic slicing**

```python
FIELD_GROUPS = {
    "document_number": "identity",
    "document_type": "identity",
    "purchase_order_number": "purchase",
    "currency": "amount",
    "subtotal": "amount",
    "tax_total": "amount",
    "total": "amount",
    "items": "line_item",
}
```

Classify missing/extra lines and Evidence gaps separately, map field roots to groups, and always create `schema_failure` for an invalid document even when its error list is empty. Add one business-scenario slice per document from `business_scenario`. Sort by `(dimension, value)`.

- [ ] **Step 5: Verify focused and legacy metrics**

Run: `uv run pytest tests/test_experiment_slicing.py tests/test_evaluation_metrics.py tests/test_evaluation_runner.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app/experiments app/evaluation/models.py tests/test_experiment_slicing.py
git commit -m "feat: add experiment contracts and error slicing"
```

---

### Task 2: Fail-Closed Promotion Decisions

**Files:**
- Create: `app/experiments/promotion.py`
- Create: `app/experiments/reporting.py`
- Test: `tests/test_experiment_promotion.py`

**Interfaces:**
- Consumes: Task 1 contracts.
- Produces: `decide_promotion(baseline: EvaluationRun, candidate: EvaluationRun, decided_by: str, now: datetime) -> PromotionDecision`; `render_promotion_markdown(decision: PromotionDecision) -> str`.

- [ ] **Step 1: Write failing gate tests**

```python
def test_fixed_slice_without_regression_is_recommended(runs):
    baseline, candidate = runs(
        baseline_accuracy="0.94",
        candidate_accuracy="0.96",
        baseline_purchase_errors=2,
        candidate_purchase_errors=0,
    )
    decision = decide_promotion(
        baseline, candidate, decided_by="admin-1", now=FIXED_NOW
    )
    assert decision.outcome == PromotionOutcome.RECOMMENDED

def test_unknown_required_cost_is_inconclusive(runs):
    baseline, candidate = runs(candidate_cost=None, require_cost=True)
    decision = decide_promotion(
        baseline, candidate, decided_by="admin-1", now=FIXED_NOW
    )
    assert decision.outcome == PromotionOutcome.INCONCLUSIVE
```

Also cover dataset mismatch, incomplete run, Schema below 1, critical-field regression, lower F1/Evidence, over-budget cost, and internal calculation failure.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_experiment_promotion.py -q`

Expected: FAIL because `app.experiments.promotion` is absent.

- [ ] **Step 3: Implement ordered checks**

Use exact codes: `dataset_identity`, `runs_complete`, `schema_valid_rate`, `critical_fields`, `field_accuracy`, `line_item_f1`, `evidence_coverage`, `cost_known`, `cost_limit`, `target_slice_improved`.

```python
if any(not check.passed for check in checks if check.hard_gate):
    outcome = PromotionOutcome.REJECTED
elif any(check.evidence_missing for check in checks):
    outcome = PromotionOutcome.INCONCLUSIVE
else:
    outcome = PromotionOutcome.RECOMMENDED
```

Catch calculation exceptions at the public boundary and return `inconclusive` with the exception class, not a stack trace.

- [ ] **Step 4: Render a safe deterministic report**

Include outcome, run IDs, dataset identity, every gate, threshold, regression, and improvement. Exclude credentials, base URLs, source documents, and complete model responses.

- [ ] **Step 5: Verify promotion and legacy comparison**

Run: `uv run pytest tests/test_experiment_promotion.py tests/test_evaluation_comparison.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app/experiments/promotion.py app/experiments/reporting.py tests/test_experiment_promotion.py
git commit -m "feat: add fail-closed model promotion gates"
```

---

### Task 3: PostgreSQL Persistence

**Files:**
- Create: `app/experiments/ports.py`
- Create: `app/infra/postgres_experiment_repository.py`
- Create: `migrations/versions/20260807_12_add_extraction_quality_lab.py`
- Modify: `app/infra/database_models.py`
- Modify: `tests/fakes.py`
- Test: `tests/test_postgres_experiment_repository.py`
- Modify: `docs/reference/12-database-dictionary.md`
- Modify: `docs/architecture/07-data-and-infrastructure.md`

**Interfaces:**
- Produces `ExperimentRepository`: `create/get/list_definition`, `create/mark_running/complete/fail/cancel/get/list_run`, `create/list/confirm_feedback`, `save/get_decision`.

- [ ] **Step 1: Write repository transition tests**

```python
def test_completion_preserves_failed_documents(repository, definition, run):
    repository.create_definition(definition)
    repository.create_run(run)
    repository.mark_run_running(run.run_id, started_at=FIXED_NOW)
    completed = repository.complete_run(
        run.run_id,
        summary=SUMMARY,
        documents=[VALID_DOCUMENT, FAILED_DOCUMENT],
        slices=SLICES,
        completed_at=FIXED_LATER,
    )
    assert completed.status == EvaluationRunStatus.COMPLETED
    assert len(completed.documents) == completed.summary.document_count == 2
```

Also test immutable definitions, legal transitions including queued/running → cancelled, Feedback confirmation, safe failures, and full Promotion check persistence.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_postgres_experiment_repository.py -q`

Expected: FAIL because the repository is absent.

- [ ] **Step 3: Add four tables**

Create `experiment_definitions`, `evaluation_runs`, `feedback_candidates`, and `promotion_decisions`. Use JSON with PostgreSQL JSONB variants for configuration/results/checks, enum CheckConstraints, FKs to admin users and runs, and indexes on run status, unconfirmed feedback, and candidate run. Add a PostgreSQL trigger rejecting update/delete of experiment definitions.

- [ ] **Step 4: Implement conditional transitions**

```python
result = session.execute(
    update(EvaluationRunRow)
    .where(
        EvaluationRunRow.run_id == run_id,
        EvaluationRunRow.status == "queued",
    )
    .values(status="running", started_at=started_at)
)
if result.rowcount != 1:
    raise ExperimentTransitionError("run must be queued")
```

Apply the same pattern to completion, failure, and cancellation. Validate `summary.document_count == len(documents)` before opening the transaction. Cancellation records `cancelled_at` and never stores a completed summary.

- [ ] **Step 5: Verify repository and migration**

Run: `uv run pytest tests/test_postgres_experiment_repository.py -q`

Run: `uv run alembic upgrade head; uv run alembic downgrade -1; uv run alembic upgrade head; uv run alembic check`

Expected: PASS.

- [ ] **Step 6: Verify docs and commit**

Run: `uv run python tools/check_documentation_sync.py --base-ref HEAD~1`

```powershell
git add app/experiments/ports.py app/infra/database_models.py app/infra/postgres_experiment_repository.py migrations/versions/20260807_12_add_extraction_quality_lab.py tests/fakes.py tests/test_postgres_experiment_repository.py docs/reference/12-database-dictionary.md docs/architecture/07-data-and-infrastructure.md
git commit -m "feat: persist extraction experiments"
```

---

### Task 4: Persisted Real-API Runner and CLI

**Files:**
- Create: `app/experiments/runner.py`
- Create: `app/cli/create_experiment.py`
- Create: `app/cli/run_experiment.py`
- Modify: `app/evaluation/runner.py`
- Modify: `app/cli/evaluate_extraction.py`
- Test: `tests/test_experiment_runner.py`
- Modify: `docs/ai/09-testing-and-evaluation.md`
- Modify: `docs/operations/08-api-ui-and-local-run.md`

**Interfaces:**
- Produces `ExperimentRunner.run(definition_id: str, output_root: Path, max_documents: int | None = None) -> EvaluationRun`.
- Definition CLI: `--name`, `--role`, `--manifest`, and threshold arguments; it reads current Parser/Normalizer/Prompt/Schema provenance from the same runtime configuration used by evaluation.
- Run CLI: `--definition-id`, `--output-root`, `--max-documents`.

- [ ] **Step 1: Write orchestration tests**

```python
def test_partial_failure_is_persisted(repository, fake_evaluator):
    fake_evaluator.result = (SUMMARY_FOR_TWO, [VALID, FAILED], RUN_DIR)
    completed = ExperimentRunner(
        repository=repository, evaluator=fake_evaluator, now=clock
    ).run("definition-1", output_root=Path("results"))
    assert completed.summary.document_count == 2
    assert any(item.value == "schema_failure" for item in completed.slices)
```

Cover evaluator exception → persisted failed, `KeyboardInterrupt` → persisted cancelled, missing definition → no run, dataset mismatch before model call, and distinct run IDs.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_experiment_runner.py -q`

Expected: FAIL because `ExperimentRunner` is absent.

- [ ] **Step 3: Add dataset hashing**

```python
def load_dataset_identity(manifest_path: Path) -> DatasetIdentityData:
    manifest_bytes = manifest_path.read_bytes()
    paths = sorted(document_paths(json.loads(manifest_bytes), manifest_path.parent))
    return DatasetIdentityData(
        manifest_sha256=sha256(manifest_bytes).hexdigest(),
        document_sha256s=tuple(
            sha256(path.read_bytes()).hexdigest() for path in paths
        ),
    )
```

Keep this helper free of database types. Copy each manifest case's `expected_outcome` into `DocumentEvaluation.business_scenario`; reject a case without that field instead of inventing an unknown scenario.

- [ ] **Step 4: Implement orchestration**

Create queued run → mark running → verify identity → call existing evaluator → slice results → complete. On execution exception, persist a stable code and safe message, then raise `ExperimentExecutionFailed`. Catch `KeyboardInterrupt` separately, persist `cancelled`, and re-raise it so the CLI exits normally for an interrupt.

- [ ] **Step 5: Share provider construction and add the definition CLI**

Move provider setup into `build_real_parser(settings)` and `build_real_normalizer(settings)`. Both evaluation CLIs reuse them. `create_experiment` hashes the selected manifest and documents, records current provider/model/Prompt/Schema/parameter provenance, creates the immutable definition, and prints only its ID. `run_experiment` loads that definition, executes it, writes a safe report, and prints run ID and aggregate metrics only.

Use an exact creation flow in the CLI test:

```python
exit_code = create_main([
    "--name", "qwen-baseline",
    "--role", "baseline",
    "--manifest", "evaluation_data/manifest.json",
    "--required-schema-valid-rate", "1",
    "--minimum-field-accuracy", "0.95",
    "--minimum-line-item-f1", "0.95",
    "--minimum-evidence-coverage", "0.90",
    "--max-cost-aud-per-document", "0.10",
])
assert exit_code == 0
```

- [ ] **Step 6: Verify**

Run: `uv run pytest tests/test_experiment_runner.py tests/test_evaluation_runner.py tests/test_evaluation_cache.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app/experiments/runner.py app/cli/create_experiment.py app/cli/run_experiment.py app/evaluation/runner.py app/cli/evaluate_extraction.py tests/test_experiment_runner.py docs/ai/09-testing-and-evaluation.md docs/operations/08-api-ui-and-local-run.md
git commit -m "feat: run persisted extraction experiments"
```

---

### Task 5: Governed Reviewer Feedback

**Files:**
- Create: `app/experiments/feedback.py`
- Test: `tests/test_experiment_feedback.py`
- Modify: `app/infra/postgres_review_repository.py`
- Modify: `docs/business/05-review-and-versioning.md`

**Interfaces:**
- Produces `FeedbackService.collect_for_version(version_id: str) -> list[FeedbackCandidate]`.
- Produces `FeedbackService.confirm(candidate_id, classification, include_in_gold, user, confirmed_at) -> FeedbackCandidate`.

- [ ] **Step 1: Write governance tests**

```python
def test_edit_generates_field_candidates(service, edited_version):
    candidates = service.collect_for_version(edited_version.version_id)
    assert {(x.field_path, x.old_value, x.new_value) for x in candidates} == {
        ("supplier.name", "SYNTHETIC DOCUMENT", "Southern Cross Foodservice")
    }

def test_only_model_error_enters_gold(service, admin):
    item = service.confirm(
        "feedback-1",
        FeedbackClassification.ACCEPTABLE_VARIANT,
        True,
        admin,
        FIXED_NOW,
    )
    assert item.include_in_gold is False
```

Cover non-admin rejection, idempotent collection, recursive dict diffs, stable line identity, and business-context updates.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_experiment_feedback.py -q`

Expected: FAIL because `FeedbackService` is absent.

- [ ] **Step 3: Expose review facts**

Add `get_action(action_id)` to the review repository and reuse current version/action reads. Do not couple `ReviewService` to experiments.

- [ ] **Step 4: Implement stable diffs**

```python
def iter_field_changes(old, new, path=""):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            child = f"{path}.{key}" if path else key
            yield from iter_field_changes(old.get(key), new.get(key), child)
        return
    if old != new:
        yield path, old, new
```

Match list items by SKU, then normalized description. Without stable identity, record one whole-list change rather than misleading positional fields.

- [ ] **Step 5: Enforce immutable confirmation**

Only admin + `model_error` can set Gold eligibility. A later changed judgment creates a superseding candidate instead of overwriting audit history.

- [ ] **Step 6: Verify and commit**

Run: `uv run pytest tests/test_experiment_feedback.py tests/test_review_service.py -q`

```powershell
git add app/experiments/feedback.py app/infra/postgres_review_repository.py tests/test_experiment_feedback.py docs/business/05-review-and-versioning.md
git commit -m "feat: govern reviewer feedback for evaluation"
```

---

### Task 6: Admin Experiment API

**Files:**
- Create: `app/api/experiment_routes.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/main.py`
- Test: `tests/test_experiment_api.py`
- Modify: `tests/test_route_governance.py`
- Modify: `docs/reference/11-api-contracts.md`

**Interfaces:** Admin endpoints for definitions, runs, decisions, feedback listing, and feedback confirmation. No endpoint executes a real experiment.

- [ ] **Step 1: Write auth and contract tests**

```python
def test_reviewer_cannot_create_experiment(reviewer_client):
    assert reviewer_client.post(
        "/api/experiments", json=VALID_DEFINITION
    ).status_code == 403

def test_admin_compares_completed_runs(admin_client):
    response = admin_client.post(
        "/api/promotion-decisions",
        json={"baseline_run_id": "run-a", "candidate_run_id": "run-b"},
    )
    assert response.status_code == 201
```

Cover 401 for every endpoint, 404, 409 transitions, malformed thresholds, and proof that no route invokes external providers.

- [ ] **Step 2: Verify 404 failures**

Run: `uv run pytest tests/test_experiment_api.py tests/test_route_governance.py -q`

Expected: FAIL until routes exist.

- [ ] **Step 3: Implement typed endpoints**

Create:
- `POST/GET /api/experiments`, `GET /api/experiments/{id}`
- `GET /api/experiment-runs`, `GET /api/experiment-runs/{id}`
- `POST /api/promotion-decisions`
- `GET /api/feedback-candidates`
- `POST /api/feedback-candidates/{id}/confirm`

Server assigns IDs, actor IDs, and timestamps. Use 201/404/409/422 consistently.

- [ ] **Step 4: Wire dependencies**

```python
@lru_cache
def get_experiment_repository() -> PostgresExperimentRepository:
    return PostgresExperimentRepository(get_session_factory())
```

Every route depends on `require_admin`.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_experiment_api.py tests/test_route_governance.py tests/test_auth_api.py -q`

```powershell
git add app/api/experiment_routes.py app/api/dependencies.py app/main.py tests/test_experiment_api.py tests/test_route_governance.py docs/reference/11-api-contracts.md
git commit -m "feat: expose admin experiment APIs"
```

---

### Task 7: Extraction Quality Lab Page

**Files:**
- Create: `frontend/src/experiments/experimentTypes.ts`
- Create: `frontend/src/experiments/experimentPresentation.ts`
- Create: `frontend/src/experiments/experimentPresentation.test.ts`
- Create: `frontend/src/experiments/ExperimentLabPage.tsx`
- Create: `frontend/src/experiments/ExperimentLabPage.test.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write honest presentation tests**

```typescript
it("does not render unknown cost as zero", () => {
  expect(formatCost(null)).toBe("Not configured");
});
it("enables Gold only for model errors", () => {
  expect(canEnterGold("model_error")).toBe(true);
  expect(canEnterGold("acceptable_variant")).toBe(false);
});
```

- [ ] **Step 2: Write page behavior tests**

Assert admin-only navigation, complete-run selection, every gate and slice, unknown cost, disabled comparison for incomplete runs, disabled Gold for non-model errors, and server refresh after confirmation.

- [ ] **Step 3: Verify missing modules**

Run: `npm test -- --run src/experiments`

Expected: FAIL because modules are absent.

- [ ] **Step 4: Implement types and pure helpers**

```typescript
export function formatCost(value: string | null): string {
  return value === null ? "Not configured" : `AUD \${value}`;
}
export function canEnterGold(value: FeedbackClassification | null): boolean {
  return value === "model_error";
}
```

- [ ] **Step 5: Implement focused sections**

Use typed `RunSelector`, `GateTable`, `SliceTable`, `DecisionSummary`, and `FeedbackQueue`. The parent page fetches; child sections receive props. Use text and semantic tables, not charts.

- [ ] **Step 6: Add admin-only route**

Show Lab navigation only for admin. Exact `/lab` renders the page. A reviewer manually visiting `/lab` sees access denied and makes no experiment requests.

- [ ] **Step 7: Verify frontend**

Run: `npm test -- --run`

Run: `npm run typecheck`

Run: `npm run build`

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add frontend/src/experiments frontend/src/app/App.tsx frontend/src/styles.css
git commit -m "feat: add extraction quality lab console"
```

---

### Task 8: Documentation and Acceptance

**Files:**
- Modify: `docs/code-document-map.json`
- Modify: `docs/ai/09-testing-and-evaluation.md`
- Modify: `docs/operations/08-api-ui-and-local-run.md`
- Modify: `docs/interview/model-selection.md`
- Modify: `README.md`
- Test: `tests/test_experiment_documentation.py`

- [ ] **Step 1: Write documentation tests**

```python
def test_quality_lab_docs_state_safety_boundaries():
    evaluation = _read("docs/ai/09-testing-and-evaluation.md")
    interview = _read("docs/interview/model-selection.md")
    assert "失败必须进入分母" in evaluation
    assert "不会自动修改生产模型配置" in evaluation
    assert "Feedback Candidate" in interview
    assert "inconclusive" in interview
```

Also assert the CLI, `/lab`, dataset identity, real-API prerequisite, and Gold confirmation rule.

- [ ] **Step 2: Verify gaps**

Run: `uv run pytest tests/test_experiment_documentation.py -q`

Expected: FAIL until docs are complete.

- [ ] **Step 3: Update the code-document map**

Map `app/experiments/**`, experiment repository/API/CLI, and frontend experiments to evaluation, review, API, database, operations, and interview docs.

- [ ] **Step 4: Document the 5–8 minute demo**

Exact order: show baseline → run one live candidate document → show provenance → compare gates → drill into one slice → classify one feedback candidate → create decision → explain why it does not deploy automatically.

- [ ] **Step 5: Run full backend**

Run: `uv run pytest --ignore=tests/test_postgres_reconciliation_case_integration.py`

Expected: PASS.

- [ ] **Step 6: Run PostgreSQL and migrations**

```powershell
uv run alembic upgrade head
uv run pytest tests/test_postgres_reconciliation_case_integration.py tests/test_postgres_experiment_repository.py
uv run alembic downgrade -1
uv run alembic upgrade head
uv run alembic current
uv run alembic heads
uv run alembic check
```

Expected: PASS with one Alembic head.

- [ ] **Step 7: Run frontend and repository checks**

```powershell
Set-Location frontend
npm test -- --run
npm run typecheck
npm run build
Set-Location ..
uv run python tools/check_documentation_sync.py --base-ref origin/main
git diff --check
```

Expected: PASS.

- [ ] **Step 8: Run baseline/candidate evidence**

Create baseline and candidate definitions in `/lab`, copy the displayed definition IDs into process-local variables, then run all 17 synthetic documents:

```powershell
$env:IVIDA_BASELINE_DEFINITION_ID = Read-Host 'Baseline definition ID'
$env:IVIDA_CANDIDATE_DEFINITION_ID = Read-Host 'Candidate definition ID'
uv run python -m app.cli.run_experiment --definition-id $env:IVIDA_BASELINE_DEFINITION_ID
uv run python -m app.cli.run_experiment --definition-id $env:IVIDA_CANDIDATE_DEFINITION_ID
```

Return to `/lab`, select the two completed runs, and create the Promotion Decision. Never commit customer documents, credentials, `.env`, complete predictions, or private Gold.

- [ ] **Step 9: Commit**

```powershell
git add README.md docs/code-document-map.json docs/ai/09-testing-and-evaluation.md docs/operations/08-api-ui-and-local-run.md docs/interview/model-selection.md tests/test_experiment_documentation.py
git commit -m "docs: explain the extraction quality workflow"
```

---

## Final Review Checklist

- [ ] Definitions contain dataset, Parser, Normalizer, Prompt, Schema, parameters, thresholds, creator, and timestamp.
- [ ] Completed runs preserve successful and failed documents.
- [ ] Only the CLI invokes real providers for experiments.
- [ ] APIs expose no credentials, base URLs, source files, or complete responses.
- [ ] Promotion requires identical identity and fails closed.
- [ ] Unknown cost remains unknown everywhere.
- [ ] Only confirmed `model_error` feedback is Gold-eligible.
- [ ] Existing review, reconciliation, Case, delivery, and auth tests stay green.
- [ ] Documentation distinguishes recommendation from deployment.
- [ ] The demo completes in 5–8 minutes using one live document plus saved full-run evidence.
