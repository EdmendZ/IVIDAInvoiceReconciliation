# 精确文件与任务归属

本表由 tasks.json 生成，仅辅助阅读；不是额外权限。未出现的文件默认只读。N=create；M=modify。

| 文件 | 任务权限 |
|---|---|
| `.env.compose.example` | T04 M |
| `.env.example` | T04 M |
| `.github/workflows/ci.yml` | T00 M |
| `AGENTS.md` | T00 N |
| `README.md` | T09 M |
| `app/api/dependencies.py` | T06 M |
| `app/api/extraction_routes.py` | T06 M |
| `app/api/reconciliation_case_routes.py` | T06 M |
| `app/api/review_routes.py` | T06 M |
| `app/api/routes.py` | T06 M |
| `app/api/upload_routes.py` | T06 M |
| `app/api/workspace_routes.py` | T06 N |
| `app/core/config.py` | T04 M |
| `app/domain/workspace.py` | T01 N, T03 M |
| `app/infra/database_models.py` | T03 M |
| `app/infra/postgres_taptouch_receiving_repository.py` | T03 M |
| `app/infra/postgres_workspace_repository.py` | T03 N |
| `app/main.py` | T06 M |
| `app/services/document_upload_service.py` | T05 M |
| `app/services/validation_service.py` | T02 M |
| `app/services/workspace_comparison.py` | T02 N |
| `app/services/workspace_matching.py` | T02 N |
| `app/services/workspace_ports.py` | T01 N |
| `app/services/workspace_service.py` | T05 N |
| `app/workers/workspace_worker.py` | T04 N |
| `compose.release.yaml` | T04 M |
| `compose.yaml` | T04 M |
| `docs/README.md` | T09 M |
| `docs/architecture/02-architecture-and-code-map.md` | T09 M |
| `docs/business/00-product-positioning.md` | T09 M |
| `docs/business/03-document-lifecycle.md` | T09 M |
| `docs/business/05-review-and-versioning.md` | T09 M |
| `docs/business/06-reconciliation-rules.md` | T09 M |
| `docs/code-document-map.json` | T00 M |
| `docs/operations/08-api-ui-and-local-run.md` | T09 M |
| `docs/operations/20-ci-cd-and-release.md` | T09 M |
| `docs/reference/11-api-contracts.md` | T09 M |
| `docs/reference/12-database-dictionary.md` | T09 M |
| `frontend/src/api/client.ts` | T07 M |
| `frontend/src/app/App.tsx` | T08 M |
| `frontend/src/cases/CaseDetailPage.test.tsx` | T08 M |
| `frontend/src/cases/CaseDetailPage.tsx` | T08 M |
| `frontend/src/cases/CaseQueuePage.tsx` | T08 M |
| `frontend/src/experiments/ExperimentLabPage.test.tsx` | T08 M |
| `frontend/src/i18n.ts` | T07 M |
| `frontend/src/reconcile/ReconciliationPage.tsx` | T08 M |
| `frontend/src/review/ReviewDocumentPage.tsx` | T08 M |
| `frontend/src/review/ReviewQueuePage.tsx` | T08 M |
| `frontend/src/review/StructuredDocumentEditor.tsx` | T08 M |
| `frontend/src/styles.css` | T08 M |
| `frontend/src/workspace/DocumentPage.test.tsx` | T08 N |
| `frontend/src/workspace/DocumentPage.tsx` | T08 N |
| `frontend/src/workspace/WorkspacePage.test.tsx` | T08 N |
| `frontend/src/workspace/WorkspacePage.tsx` | T08 N |
| `frontend/src/workspace/workspaceClient.test.ts` | T07 N |
| `frontend/src/workspace/workspaceClient.ts` | T07 N |
| `frontend/src/workspace/workspacePresentation.test.ts` | T07 N |
| `frontend/src/workspace/workspacePresentation.ts` | T07 N |
| `frontend/src/workspace/workspaceTypes.ts` | T07 N |
| `migrations/versions/20260916_15_workspace.py` | T03 N |
| `run_workspace_worker.py` | T04 N |
| `scripts/local_demo_common.ps1` | T04 M |
| `start_local_demo.ps1` | T04 M |
| `stop_local_demo.ps1` | T04 M |
| `tests/fixtures/workspace_scenarios.json` | T09 N |
| `tests/test_delivery_configuration.py` | T04 M |
| `tests/test_document_upload_service.py` | T05 M |
| `tests/test_harness_guards.py` | T00 N |
| `tests/test_postgres_workspace_repository.py` | T03 N |
| `tests/test_validation_service.py` | T02 M |
| `tests/test_workspace_acceptance.py` | T09 N |
| `tests/test_workspace_api.py` | T06 N |
| `tests/test_workspace_comparison.py` | T02 N |
| `tests/test_workspace_contracts.py` | T01 N, T03 M |
| `tests/test_workspace_harness_acceptance.py` | T10 N |
| `tests/test_workspace_legacy_gate.py` | T06 N |
| `tests/test_workspace_matching.py` | T02 N |
| `tests/test_workspace_service.py` | T05 N |
| `tests/test_workspace_worker.py` | T04 N |
| `tools/check_spec_contract.py` | T00 N |
| `tools/check_task_scope.py` | T00 N |
