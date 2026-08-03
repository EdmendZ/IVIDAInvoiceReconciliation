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
- 开发诊断端点与真实批准版本流程明确分离。
