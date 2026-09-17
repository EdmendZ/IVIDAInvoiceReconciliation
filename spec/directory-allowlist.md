# 精确文件与任务归属

本表由 tasks.json 生成，仅辅助阅读；不是额外权限。未出现的文件默认只读。N=create；M=modify。

| 文件 | 任务权限 |
|---|---|
| `.env.compose.example` | T04 M |
| `.env.example` | T04 M |
| `.github/workflows/ci.yml` | T00 M, T09 M |
| `AGENTS.md` | T00 N |
| `README.md` | T09 M, T12 M, T13 M |
| `app/api/dependencies.py` | T06 M |
| `app/api/extraction_routes.py` | T06 M |
| `app/api/reconciliation_case_routes.py` | T06 M |
| `app/api/review_routes.py` | T06 M |
| `app/api/routes.py` | T06 M |
| `app/api/upload_routes.py` | T06 M |
| `app/api/workspace_routes.py` | T06 N, T17 M |
| `app/core/config.py` | T04 M |
| `app/domain/documents.py` | T14 M |
| `app/domain/workspace.py` | T01 N, T03 M, T16 M, T17 M |
| `app/infra/database_models.py` | T03 M |
| `app/infra/postgres_taptouch_receiving_repository.py` | T03 M |
| `app/infra/postgres_workspace_repository.py` | T03 N, T14 M, T16 M, T17 M |
| `app/main.py` | T06 M |
| `app/resources/prompts/normalize_document_system.txt` | T14 M |
| `app/services/document_upload_service.py` | T05 M |
| `app/services/validation_service.py` | T02 M, T14 M |
| `app/services/workspace_comparison.py` | T02 N |
| `app/services/workspace_matching.py` | T02 N, T14 M |
| `app/services/workspace_ports.py` | T01 N, T17 M |
| `app/services/workspace_service.py` | T05 N, T17 M |
| `app/workers/workspace_worker.py` | T04 N |
| `compose.release.yaml` | T04 M |
| `compose.yaml` | T04 M |
| `docs/README.md` | T09 M |
| `docs/ai.md` | T14 M |
| `docs/architecture.md` | T03 M, T09 M, T14 M, T16 M, T17 M |
| `docs/code-document-map.json` | T00 M, T12 M, T13 M |
| `docs/development.md` | T09 M, T12 M, T13 M, T15 M |
| `docs/product.md` | T09 M, T12 M, T16 M, T17 M |
| `frontend/src/api/client.ts` | T07 M |
| `frontend/src/app/App.tsx` | T08 M, T16 M, T17 M |
| `frontend/src/cases/CaseDetailPage.test.tsx` | T08 M |
| `frontend/src/cases/CaseDetailPage.tsx` | T08 M |
| `frontend/src/cases/CaseQueuePage.tsx` | T08 M |
| `frontend/src/experiments/ExperimentLabPage.test.tsx` | T08 M |
| `frontend/src/history/HistoryPage.test.tsx` | T17 N |
| `frontend/src/history/HistoryPage.tsx` | T17 N |
| `frontend/src/i18n.ts` | T07 M |
| `frontend/src/reconcile/ReconciliationPage.tsx` | T08 M |
| `frontend/src/review/ReviewDocumentPage.tsx` | T08 M |
| `frontend/src/review/ReviewQueuePage.tsx` | T08 M |
| `frontend/src/review/StructuredDocumentEditor.tsx` | T08 M |
| `frontend/src/styles.css` | T08 M, T16 M, T17 M |
| `frontend/src/workspace/DocumentPage.test.tsx` | T08 N, T16 M |
| `frontend/src/workspace/DocumentPage.tsx` | T08 N, T16 M |
| `frontend/src/workspace/WorkspacePage.test.tsx` | T08 N, T16 M |
| `frontend/src/workspace/WorkspacePage.tsx` | T08 N, T16 M |
| `frontend/src/workspace/workspaceClient.test.ts` | T07 N |
| `frontend/src/workspace/workspaceClient.ts` | T07 N, T17 M |
| `frontend/src/workspace/workspacePresentation.test.ts` | T07 N, T16 M |
| `frontend/src/workspace/workspacePresentation.ts` | T07 N |
| `frontend/src/workspace/workspaceTypes.ts` | T07 N, T14 M, T16 M, T17 M |
| `migrations/versions/20260916_15_workspace.py` | T03 N |
| `run_local_demo.py` | T12 N |
| `run_workspace_worker.py` | T04 N |
| `scripts/local_demo_common.ps1` | T04 M, T15 M |
| `setup_demo_data.py` | T13 N |
| `setup_dev_admin.py` | T12 N |
| `start_local_demo.ps1` | T04 M |
| `stop_local_demo.ps1` | T04 M |
| `tests/fixtures/workspace_scenarios.json` | T09 N |
| `tests/test_delivery_configuration.py` | T04 M |
| `tests/test_demo_data_entrypoint.py` | T13 N |
| `tests/test_dev_entrypoints.py` | T12 N, T15 M |
| `tests/test_document_upload_service.py` | T05 M |
| `tests/test_harness_guards.py` | T00 N |
| `tests/test_normalization_provider.py` | T14 M |
| `tests/test_postgres_workspace_repository.py` | T03 N, T16 M, T17 M |
| `tests/test_validation_service.py` | T02 M, T14 M |
| `tests/test_workspace_acceptance.py` | T09 N |
| `tests/test_workspace_api.py` | T06 N, T17 M |
| `tests/test_workspace_comparison.py` | T02 N |
| `tests/test_workspace_contracts.py` | T01 N, T03 M, T16 M, T17 M |
| `tests/test_workspace_harness_acceptance.py` | T10 N |
| `tests/test_workspace_legacy_gate.py` | T06 N |
| `tests/test_workspace_matching.py` | T02 N, T14 M |
| `tests/test_workspace_service.py` | T05 N, T17 M |
| `tests/test_workspace_worker.py` | T04 N |
| `tools/check_spec_contract.py` | T00 N |
| `tools/check_task_scope.py` | T00 N |
