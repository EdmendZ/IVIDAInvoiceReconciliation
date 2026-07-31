# PostgreSQL 数据字典

## 总览

SQLAlchemy 映射位于 `app/infra/database_models.py`，Schema 演进位于
`migrations/versions/`。本文件解释每张表承担的业务职责，字段的精确类型仍以
迁移和 ORM 为准。

## 抽取域

### `extraction_tasks`

一份上传原件的长期业务对象。

| 字段组 | 关键字段 | 含义 |
|---|---|---|
| 身份 | task_id | UUID |
| 分类 | document_type | invoice / receive_note |
| 文件 | original_filename、content_type、size_bytes、sha256 | 原件元数据 |
| 存储 | storage_bucket、storage_object_key | MinIO 定位 |
| 业务提示 | purchase_order_hint | 用户输入的 PO 提示 |
| 状态 | status、error_message | 文件级处理状态 |
| 时间 | created_at、updated_at | 创建与最后变化 |

### `extraction_runs`

一次具体处理尝试，是异步状态机的核心表。

| 字段组 | 关键字段 |
|---|---|
| 关系 | run_id、task_id |
| 状态 | status、attempt_count、next_attempt_at |
| 远端 | remote_job_id |
| 租约 | lease_owner、lease_expires_at |
| 错误 | phase_error_code、error_message |
| 结果 | raw_output、normalized_output |
| 成本 | input_tokens、output_tokens、estimated_cost_aud |
| 溯源 | parser_provider/model、normalizer_provider/model、prompt_version |
| 取消 | cancel_requested_at/by、cancelled_stage、remote_may_continue |
| 时间 | started_at、completed_at、created_at、normalization_latency_ms |

同一个 Task 可以有多个 Run，因此失败重试不会覆盖历史。

### `parse_results`

保存 MinerU 的可查询结果：

- remote_job_id；
- MinIO ZIP 对象键；
- Markdown；
- content_blocks；
- tables；
- page_count。

### `document_drafts`

成功 Run 生成的机器草稿，包含规范化 JSON 和 `reviewable/blocked` 状态。

### `field_evidence`

每条记录将 Draft 字段指向原文：

- field_path；
- value；
- page；
- source_text；
- block/table/row 定位；
- confidence。

### `validation_issues`

保存机器 Draft 的规则问题：

- rule_code；
- warning/blocking；
- field_path；
- message；
- measured_difference；
- resolved_at。

## 认证与审核域

### `admin_users`

保存用户、Argon2 password_hash、role、is_active。绝不保存明文密码。

### `admin_sessions`

数据库只保存 Session Token Hash，而不是浏览器持有的原 Token。Session 有明确
过期时间，用户删除时级联删除。

### `document_versions`

人工审核版本：

- task_id 和 source_draft_id；
- version_number；
- document_type 和 document_json；
- draft/approved/rejected；
- created_by、approved_by、approved_at。

`task_id + version_number` 唯一。Draft 使用 RESTRICT 关系，避免有 Version 时
删除来源 Draft。

### `review_actions`

追加式审核日志：

- version_id；
- actor_user_id；
- action；
- field_path；
- old_value/new_value；
- reason；
- created_at。

用于解释谁启动审核、修改、重分类、批准或驳回。

## 核对域

### `reconciliations`

一次核对的头记录：

- invoice_version_id；
- result_json；
- created_by；
- created_at。

### `reconciliation_receive_notes`

Reconciliation 与 Receive Note Version 的多对多连接表。联合主键防止同一
Receive Note 在同一次核对中重复加入。

### `reconciliation_line_results`

逐商品行结果，`reconciliation_id + line_index` 唯一。头表保留完整 JSON，
行表支持以后按差异行查询和统计。

## 运行状态

### `worker_heartbeats`

一行代表一个 Worker：

- worker_id；
- version；
- started_at；
- last_seen_at。

它不保存队列任务，也不替代 extraction_runs。

## 重要外键删除策略

| 关系 | 策略 | 原因 |
|---|---|---|
| Task -> Run/Draft/Version | CASCADE 为主 | 删除 Task 时清理处理数据 |
| Draft -> Version | RESTRICT | 有人工版本时不能删除来源 |
| Version -> Reconciliation | RESTRICT | 历史核对引用的批准版本不能删除 |
| User -> Version/Action/Result | RESTRICT | 审计主体不能被静默移除 |
| Reconciliation -> Lines/Join | CASCADE | 删除头记录时清理组成部分 |

生产环境通常不直接物理删除财务记录，还需增加保留与法律冻结策略。

## JSONB 为什么仍然合理

标准字段由 Pydantic 约束，但不同供应商单据可能逐步扩展。Version 和 Result
使用 JSON/JSONB 可以：

- 保存当时完整业务快照；
- 避免每次新增可选字段都立即拆表；
- 让核对结果与历史版本保持一致。

高频检索字段仍应显式建列或索引，不能把所有查询都推给无索引 JSONB。

## 面试复习点

- Task:Run 是一对多；
- Draft 是机器结果，Version 是人工结果；
- 核对引用 Version，而不是可变化的 Task；
- Session 保存 Hash；
- RESTRICT 保护审计链，CASCADE 清理真正的组成对象；
- JSONB 保存快照，但不替代关系设计。
