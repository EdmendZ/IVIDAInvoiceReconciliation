# 源码调用链导读

## 用一次完整操作串起代码

以下沿着“一张 Invoice 加两张 Receive Notes”追踪真实调用路径。阅读源码时不要
从所有 Repository 开始，而应先沿业务调用链建立整体理解。

## 1. 前端上传

入口：

- `frontend/src/upload/UploadPage.tsx`
- `app/api/upload_routes.py::upload_document`
- `app/services/document_upload_service.py::upload`

调用链：

```text
UploadPage
  -> POST /api/documents/upload
  -> require_reviewer
  -> DocumentUploadService.upload
  -> MinioObjectStorage.put
  -> PostgresExtractionTaskRepository.create
```

重点观察：

- API 只读取有限字节，防止超大上传；
- Service 使用 Magic Bytes，不信任浏览器 MIME；
- MinIO 成功、数据库失败时会补偿删除对象。

## 2. 创建抽取 Run

入口：

- `app/api/extraction_routes.py::start_extraction`
- `app/services/extraction_service.py::queue`

`queue()` 验证 Task 状态后创建 `queued` Run，并将 Task 更新为 extracting。
它不会在 HTTP 请求内调用 MinerU。

## 3. Worker 推进

入口：

- `run_extraction_worker.py`
- `app/workers/extraction_worker.py::run_forever`
- `app/workers/extraction_worker.py::run_once`

阶段：

```text
claim_next
  -> _submit
  -> _poll
  -> _normalize
  -> create Draft
  -> ready_for_review
```

每次 `run_once` 只推进一个阶段或重新调度。关键状态写入 PostgreSQL，MinerU
ZIP 写入 MinIO。

## 4. MinerU 与 LLM

Parser Contract：

- `app/domain/parsing.py`
- `app/infra/mineru_parser.py`

Normalizer Contract：

- `app/domain/normalization.py`
- `app/infra/openai_normalization_provider.py`

Prompt：

- `app/resources/prompts/normalize_document_system.txt`
- `app/resources/prompts/normalize_document_user.txt`

重点观察 Provider 如何把第三方异常转成 `ExternalServiceError`，以及归一化输出
如何通过 `NormalizedDocumentEnvelope` 和目标单据 Pydantic Model 双重校验。

## 5. 生成 Draft 与规则问题

入口：

- `app/services/validation_service.py`
- `app/infra/postgres_draft_repository.py`

Worker 将 Document、Evidence、Validation Issues 一起写入。Draft 的 blocked
只表示存在 Blocking Issue；它仍可进入人工审核并被修正。

## 6. 人工审核

入口：

- `frontend/src/review/ReviewQueuePage.tsx`
- `frontend/src/review/ReviewDocumentPage.tsx`
- `app/api/review_routes.py`
- `app/services/review_service.py`

重要方法：

| 方法 | 作用 |
|---|---|
| start_review | 幂等创建 Version 1 |
| preview_validation | 不落库的即时检查 |
| save_edit | 创建下一版本 |
| reclassify | 修正类型并记录动作 |
| approve | 服务端重验并批准 |
| reject | 要求原因并驳回 |

## 7. 获取候选

入口：

- `frontend/src/reconcile/ReconciliationPage.tsx`
- `app/api/routes.py::list_reconciliation_candidates`
- `ReconciliationApplicationService.list_candidates`
- `candidate_matching_service.assess_candidate`

Application Service 先要求 Invoice Version 已批准，再遍历已批准 Receive Notes。
纯候选函数不访问数据库。

## 8. 执行一对多核对

入口：

- `app/api/routes.py::create_reconciliation`
- `ReconciliationApplicationService.compare`
- `reconciliation_service.reconcile`
- `PostgresReconciliationRepository.create`

`compare()` 负责信任门禁和持久化；`reconcile()` 负责纯算法。这种分离让规则
单元测试无需数据库。

## 9. 模型评测

入口：

- `app/cli/evaluate_extraction.py`
- `app/evaluation/runner.py`
- `app/evaluation/cache.py`
- `app/evaluation/field_metrics.py`
- `app/evaluation/report.py`

它不写生产 Draft/Version 表，而是输出到 Git 忽略的 evaluation_data/results。
因此模型实验不会污染人工审核业务数据。

## 如何定位 Bug

| 现象 | 优先阅读 |
|---|---|
| 上传 422 | upload_routes、document_upload_service |
| 一直 queued | extraction_run repository、worker、runtime status |
| MinerU 重复提交 | worker `_submit`、remote_job_id、evaluation cache |
| JSON 解析失败 | normalization provider、Prompt、输出上限 |
| 审核无法批准 | review_service、validation_service |
| 候选不合理 | candidate_matching_service 及 signals |
| 数量比对错误 | reconciliation_service `_aggregate` |
| 评测分数异常 | field_metrics、Gold、evidence path |

## 推荐源码阅读顺序

1. `app/domain/documents.py`
2. `app/domain/extraction_tasks.py`
3. `app/domain/extraction_runs.py`
4. `app/services/document_upload_service.py`
5. `app/workers/extraction_worker.py`
6. `app/services/review_service.py`
7. `app/services/candidate_matching_service.py`
8. `app/services/reconciliation_service.py`
9. `app/evaluation/runner.py`
10. 最后阅读 PostgreSQL Repository 和 API 路由

先理解业务再读基础设施，可以避免把 SQLAlchemy 字段误当成架构本身。
