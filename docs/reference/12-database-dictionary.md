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

逐商品行结果，`reconciliation_id + line_index` 唯一。额外的
`(line_result_id, reconciliation_id)` 唯一键供 Case Item 的复合外键使用，确保
Item 不能引用另一次 Reconciliation 的业务行。头表保留完整 JSON，行表支持以后
按差异行查询和统计。

### `reconciliation_cases`

一个异常 Reconciliation 对应一个可分派、带乐观锁版本的人工处理 Case。

| 字段 | 类型/可空 | 关系或含义 |
|---|---|---|
| case_id | varchar(36)，非空 | 主键 |
| reconciliation_id | varchar(36)，非空 | 外键到 `reconciliations.reconciliation_id`，删除头记录时 CASCADE；全表唯一，确保一次核对最多一个 Case |
| status | varchar(32)，非空 | `unassigned`、`in_progress`、`pending_approval`、`pending_void`、`approved`、`voided` |
| assignee_user_id | varchar(36)，可空 | 外键到 `admin_users.user_id`，RESTRICT |
| revision | integer，非空 | 从 1 开始的乐观锁版本 |
| created_by | varchar(36)，非空 | 创建用户外键到 `admin_users.user_id`，RESTRICT |
| created_at | timestamptz，非空 | 创建时间 |
| claimed_at | timestamptz，可空 | 最近认领时间 |
| submitted_at | timestamptz，可空 | 最近提交审批/作废时间 |
| completed_at | timestamptz，可空 | 批准或作废时间 |

索引包括 `status`、`assignee_user_id` 和用于稳定分页的
`(created_at, case_id)`。`reconciliation_id` 唯一约束同时提供唯一索引。
`revision >= 1` 与允许的状态值由 PostgreSQL Check Constraint 保证。
`(case_id, reconciliation_id)` 也是唯一键，供 Item 同时校验 Case 身份和
Reconciliation 归属。

### `case_items`

Case 中需要逐项处理的行级或头级异常。

| 字段 | 类型/可空 | 关系或含义 |
|---|---|---|
| item_id | varchar(36)，非空 | 主键 |
| case_id | varchar(36)，非空 | 与 reconciliation_id 组成复合外键到 `reconciliation_cases`，CASCADE |
| reconciliation_id | varchar(36)，非空 | 同时参与 Case 与行结果的 ownership 复合外键 |
| item_type | varchar(32)，非空 | `line`、`purchase_order_conflict`、`currency_conflict` |
| line_result_id | varchar(36)，可空 | 行项时必填；与 reconciliation_id 组成复合外键到 `reconciliation_line_results`，RESTRICT |
| resolution_type | varchar(32)，可空 | `business_exception`、`document_data_error`、`matching_error`、`waiting_for_documents` |
| resolution_note | text，可空 | 有 resolution_type 时必须为去除空白后非空的说明 |
| resolved_by | varchar(36)，可空 | 有 resolution_type 时必填；外键到 `admin_users.user_id`，RESTRICT |
| resolved_at | timestamptz，可空 | 有 resolution_type 时必填 |
| updated_at | timestamptz，非空 | 最近修改时间 |

普通索引 `ix_case_items_case_id` 支持按 Case 取项。两个部分唯一索引分别保证：

- `uq_case_items_line_result (case_id, line_result_id)` 在
  `line_result_id IS NOT NULL` 时唯一；
- `uq_case_items_header_type (case_id, item_type)` 在 `item_type <> 'line'`
  时唯一。

因此一个 Case 可有多条不同的行项，但同一种头级冲突最多一条。Check Constraint
还保证 `item_type='line'` 当且仅当 `line_result_id` 非空，并保证已选择处理类型
时 note、resolved_by、resolved_at 完整。`(case_id, reconciliation_id)` 与
`(line_result_id, reconciliation_id)` 两个复合外键在数据库层保证行项只能属于
当前 Case 所关联的 Reconciliation；`(item_id, case_id)` 唯一键供 Action 校验归属。

### `case_actions`

Case 与 Item 变更的追加式审计日志。

| 字段 | 类型/可空 | 关系或含义 |
|---|---|---|
| action_id | varchar(36)，非空 | 主键 |
| case_id | varchar(36)，非空 | 外键到 `reconciliation_cases.case_id`，CASCADE |
| item_id | varchar(36)，可空 | 与 case_id 组成复合外键到 `case_items (item_id, case_id)`，RESTRICT，禁止跨 Case 审计引用 |
| actor_user_id | varchar(36)，非空 | 操作人外键到 `admin_users.user_id`，RESTRICT |
| action | varchar(64)，非空 | `created`、`claimed`、`reassigned`、`resolution_changed`、`submitted_for_approval`、`submitted_for_void`、`returned`、`approved`、`voided` |
| old_value | jsonb，可空 | 变更前审计值 |
| new_value | jsonb，可空 | 变更后审计值 |
| reason | text，可空 | 操作原因 |
| created_at | timestamptz，非空 | 操作时间 |

索引 `(case_id, created_at, action_id)` 支持按 Case 稳定读取时间线；Action
允许值由 Check Constraint 保证。

### Case 不可变触发器与回滚顺序

- `trg_case_actions_immutable` 拒绝 `case_actions` 的 UPDATE 和 DELETE，日志只能追加；
- `trg_reconciliation_cases_terminal_immutable` 在旧状态为 `approved` 或 `voided`
  时拒绝 Case 的 UPDATE 和 DELETE；
- `trg_case_items_terminal_immutable` 对 Item 的 INSERT、UPDATE 和 DELETE 查询并
  锁定 NEW/OLD 所属 Case，在父 Case 为上述终态时拒绝写入；初始原子创建先插入
  `unassigned` Case，因此仍可正常创建 Item。

迁移回滚先删除三个触发器及其函数，再按依赖顺序删除 `case_actions`、
`case_items`、`reconciliation_cases`，最后删除行结果上的复合唯一键；不会先删父表
破坏外键关系。

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
