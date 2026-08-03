# API 契约参考

## 阅读方式

本项目的 OpenAPI 页面位于 `/docs`，本文件重点解释端点在业务流程中的位置、
权限和状态语义。除健康检查和登录外，业务端点都需要有效的
`ivida_review_session` Cookie。

## 认证端点

| 方法 | 路径 | 用途 | 常见状态 |
|---|---|---|---|
| POST | `/api/auth/login` | 用户名密码换 Session Cookie | 200、401 |
| POST | `/api/auth/logout` | 删除数据库 Session 和 Cookie | 204 |
| GET | `/api/auth/me` | 获取当前用户与角色 | 200、401、403 |

Session Cookie：

- 名称：`ivida_review_session`；
- HttpOnly：JavaScript 不能读取；
- SameSite：Lax；
- 有效期：8 小时；
- `APP_ENV=prod` 时启用 Secure。

## 健康与运行状态

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/health` | 无 | 仅说明 API 进程可响应 |
| GET | `/api/runtime/status` | reviewer | 返回 Worker online/offline 与最近心跳 |

`/api/health=200` 不代表 Worker、MinerU、MinIO 和完整业务链路一定可用。

## 上传与 Task

### `POST /api/documents/upload`

请求：`multipart/form-data`

| 字段 | 必填 | 说明 |
|---|---|---|
| document_type | 是 | `invoice` 或 `receive_note` |
| file | 是 | PDF、PNG、JPG、JPEG |
| purchase_order_hint | 否 | 用户已知的 PO 提示，不替代模型抽取 |

成功返回 `201` 和 `ExtractionTask`。服务会根据 Magic Bytes 验证真实类型。

### `GET /api/extraction-tasks`

返回最近 Task 及其 `latest_run`。`limit` 范围为 1–200，默认 50。

### `GET /api/extraction-tasks/{task_id}`

返回单个文件级 Task。不存在返回 404；存储暂时不可用返回 503。

## Extraction Run

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/extraction-tasks/{task_id}/extract` | 为上传 Task 创建 Run |
| GET | `/api/extraction-runs/{run_id}` | 查询阶段、错误、Token 和模型信息 |
| GET | `/api/extraction-runs/{run_id}/result` | 查询 Parse、Draft、Evidence、Issues |
| POST | `/api/extraction-runs/{run_id}/cancel` | 请求协作式取消 |

创建抽取返回 `202`，因为它只完成排队，不等待 MinerU/LLM。

Result 中的 `approval_allowed` 固定为 false，提醒调用方不能从机器 Draft 直接
批准；批准必须进入 Review Version 流程。

取消语义：

- queued 通常立即进入 cancelled；
- parsing/normalizing 在 Worker 阶段边界停止；
- 已完成或已进入审核的 Run 返回 409；
- `remote_may_continue=true` 表示远端服务可能仍在运行。

## Review

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/review/tasks` | 审核队列 |
| GET | `/api/review/approved-versions` | 可用于核对的批准版本 |
| POST | `/api/review/tasks/{task_id}/start` | 幂等创建/读取首个 Version |
| GET | `/api/review/versions/{version_id}` | Version、Evidence、Issues、Model Run |
| POST | `/api/review/versions/{version_id}/validate` | 编辑时实时预校验 |
| PATCH | `/api/review/versions/{version_id}` | 保存为新版本 |
| POST | `/api/review/versions/{version_id}/reclassify` | 修正类型并创建新版本 |
| POST | `/api/review/versions/{version_id}/approve` | 批准最新无阻断版本 |
| POST | `/api/review/versions/{version_id}/reject` | 驳回并记录原因 |

### Approve 请求

```json
{
  "reason": "Source document verified",
  "confirmed_document_type": "invoice"
}
```

`confirmed_document_type` 必须与 Version 类型一致。存在阻断问题、不是最新版本
或版本已不可变时返回 409。

### Validate 与 Approve 的区别

- Validate 是无持久化的预览，帮助前端即时显示错误；
- Approve 会在服务端重新校验，并实际改变版本状态。

不能把 Validate 成功当成批准完成。

## Reconciliation

### `GET /api/reconciliations/candidates`

查询参数：`invoice_version_id`

只接受已批准 Invoice Version。返回所有已批准 Receive Note 的候选分数、
confidence、recommended 和信号列表。

### `POST /api/reconciliations`

```json
{
  "invoice_version_id": "approved-invoice-version-id",
  "receive_note_version_ids": [
    "approved-note-version-id-1",
    "approved-note-version-id-2"
  ]
}
```

应用层会重新验证所有版本状态和类型，执行核对并保存结果。任一版本未批准或
类型错误返回 409。

### `GET /api/reconciliations/{reconciliation_id}/export.csv`

要求 reviewer/admin 身份。接口读取创建核对时保存的不可变结果快照并返回
`text/csv` 附件，不会用当前版本代码重新计算历史结果。文件包含核对元数据、
判定状态和逐行数量、单价、金额差异；文本字段会防止 Excel 公式注入，记录不
存在时返回 404。

## Reconciliation Case

所有 Case 接口要求有效 Session，Reviewer 和 Admin 都可查询；只有当前负责人可
修改处理结论或提交，只有 Admin 可重新分派和作最终决定。客户端不得在请求体中
传操作者 ID，服务端始终使用 Session 对应用户。

| 方法 | 路径 | 角色与用途 |
|---|---|---|
| GET | `/api/reconciliation-cases` | Reviewer/Admin；查询待办和历史 Case |
| GET | `/api/reconciliation-cases/assignees` | Admin；列出可分派的 active Reviewer |
| GET | `/api/reconciliation-cases/{case_id}` | Reviewer/Admin；查询详情与审计历史 |
| POST | `/api/reconciliation-cases/{case_id}/claim` | Reviewer；认领未分派 Case |
| POST | `/api/reconciliation-cases/{case_id}/reassign` | Admin；重新分派非终态、已有负责人的 Case |
| PUT | `/api/reconciliation-cases/{case_id}/items/{item_id}/resolution` | 当前负责人；设置处理类型和备注 |
| POST | `/api/reconciliation-cases/{case_id}/submit-approval` | 当前负责人；提交批准申请 |
| POST | `/api/reconciliation-cases/{case_id}/submit-void` | 当前负责人；提交作废申请 |
| POST | `/api/reconciliation-cases/{case_id}/approve` | Admin；批准 `pending_approval` Case |
| POST | `/api/reconciliation-cases/{case_id}/return` | Admin；退回待决 Case 并记录原因 |
| POST | `/api/reconciliation-cases/{case_id}/void` | Admin；作废 `pending_void` Case |

### 列表查询与响应

`GET /api/reconciliation-cases` 支持：

- 重复 `status` 参数，例如
  `?status=pending_approval&status=pending_void`；
- `assignment=all|mine|unassigned`，默认 `all`；
- `invoice_number` 精确或前缀搜索；
- `page` 从 1 开始，`page_size` 默认 50，范围 1–100。

列表按 `created_at ASC, case_id ASC` 稳定排序。响应为：

```json
{
  "items": [
    {
      "case": {
        "case_id": "case-id",
        "reconciliation_id": "reconciliation-id",
        "status": "in_progress",
        "assignee_user_id": "reviewer-id",
        "revision": 3,
        "created_by": "creator-id",
        "created_at": "2026-08-03T12:00:00Z",
        "claimed_at": "2026-08-03T12:05:00Z",
        "submitted_at": null,
        "completed_at": null
      },
      "invoice_number": "INV-001",
      "receive_note_numbers": ["RN-001"],
      "actionable_count": 2,
      "assignee_username": "reviewer-a"
    }
  ],
  "page": 1,
  "page_size": 50,
  "total": 1
}
```

### 详情与变更响应

详情和每个成功变更都返回相同的 `CaseDetail`：`case` 当前状态、`items` 处理项、
负责人展示名 `assignee_username`、带 `actor_username` 的追加式 `actions`、
带数据库稳定标识的只读 `line_results`，以及创建 Case 时保存的不可变
`reconciliation` 快照。前端应以响应中的新 `revision` 作为下一次变更的
`expected_revision`。

- `case`：`case_id`、`reconciliation_id`、`status`、`assignee_user_id`、
  `revision`、`created_by`、`created_at`、`claimed_at`、`submitted_at`、
  `completed_at`；
- `items[]`：`item_id`、`case_id`、`item_type`、`line_result_id`、
  `resolution_type`、`resolution_note`、`resolved_by`、`resolved_at`、
  `updated_at`；
- `assignee_username`：当前负责人的安全展示名，未分派时为 `null`；
- `line_results[]`：`line_result_id` 与不可变业务 `line` 的配对，使 Line Item
  能明确展示 SKU、描述、数量和金额差异；头部冲突 Item 不关联商品行；
- `actions[]`：嵌套 `action`（ID、Case/Item/Actor、动作类型、旧值、新值、
  原因、时间）和安全展示字段 `actor_username`；
- `reconciliation`：不可变的版本引用、原始 `result`、创建人和创建时间。

认领、提交批准、提交作废、批准和最终作废请求：

```json
{"expected_revision": 3}
```

设置处理结论请求：

```json
{
  "resolution_type": "business_exception",
  "note": "Supplier approved short delivery",
  "expected_revision": 3
}
```

`resolution_type` 可取 `business_exception`、`document_data_error`、
`matching_error`、`waiting_for_documents`，`note` 必须非空。

重新分派请求：

```json
{
  "assignee_user_id": "active-reviewer-id",
  "reason": "Balance current workload",
  "expected_revision": 3
}
```

退回请求：

```json
{
  "reason": "Clarify supplier approval",
  "expected_revision": 4
}
```

`assignees` 仅返回 `[{"user_id": "...", "username": "..."}]`，不会返回
Password Hash、Session 或角色之外的账号资料。重新分派目标必须来自 active
Reviewer；inactive Reviewer、Admin 或不存在账号会返回 `CASE_INVALID_ASSIGNEE`。

状态流转为 `unassigned → in_progress → pending_approval → approved`，或
`in_progress → pending_void → voided`；Admin 退回时从两种 pending 状态回到
`in_progress`。`approved` 和 `voided` 是不可变终态。

Case 业务错误统一为：

```json
{"detail": {"code": "CASE_REVISION_CONFLICT", "message": "..."}}
```

`CASE_REVIEWER_REQUIRED`、`CASE_ASSIGNEE_REQUIRED` 和 `CASE_ADMIN_REQUIRED` 属于
权限拒绝并返回 403；404 和其余状态/并发 409 的稳定 code 见《错误码与分层排障》。
请求缺字段、空原因、
空备注、非法枚举或越界分页由 Schema 校验返回 422。

独立 GET 详情保证 Case、Items 与 Actions 来自同一 revision。成功 mutation 的详情
明确锚定该请求刚提交的 revision；即使另一位用户随后立即推进 Case，也不会把后续
状态误装进前一请求的成功响应。

## 开发诊断端点

只有 `APP_ENV=dev` 时注册：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/reconciliations/example` | 返回原始 JSON 示例 |
| POST | `/api/reconciliations/compare` | 跳过版本门禁直接比较 JSON |

它们用于开发测试，不应作为生产业务流程。

## HTTP 状态语义

| 状态 | 在本项目中的含义 |
|---:|---|
| 200 | 查询或同步业务操作成功 |
| 201 | 原件与 Task 已创建 |
| 202 | Run 已排队，尚未完成 |
| 204 | 登出成功且无响应体 |
| 401 | 未登录或 Session 无效 |
| 403 | 已登录但角色不允许 |
| 404 | Task、Run、Draft 或 Version 不存在 |
| 409 | 当前业务状态不允许操作 |
| 422 | 文件、Schema、驳回原因等输入不合法 |
| 503 | 存储或依赖暂时不可用 |

## 面试复习点

- 202 只表示排队，不表示抽取成功；
- 409 表达状态冲突，而不是通用服务器错误；
- Draft Result 不提供批准捷径；
- Review 和 Reconciliation 都有服务端门禁；
- Case 每次变更都携带 revision，并返回统一详情读模型；
- 开发诊断端点与真实批准版本流程明确分离。
