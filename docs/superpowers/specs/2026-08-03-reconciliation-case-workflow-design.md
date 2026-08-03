# Reconciliation 差异处理闭环设计

## 背景与目标

当前系统已经能够从人工批准的 Invoice 与 Receive Note Version 生成不可变的
确定性对账结果，并指出数量、单价、金额、缺失商品、PO 和币种差异。现有能力
回答“哪里不同”，但还不能回答“谁在处理、为何接受、何时批准、为何作废”。

本阶段增加一个独立的差异处理 Case 工作流，使异常对账能够被认领、逐项处理、
提交管理员审批、退回修改或作废，并留下不可覆盖的审计轨迹。

本阶段的成功标准是可可靠使用的 Pilot，而不只是界面演示：严格权限、状态门禁、
并发冲突保护、不可变终态和完整自动化测试均属于验收范围。

## 范围

### 包含

- 为 `requires_review=true` 的已持久化 Reconciliation 自动创建 Case；
- 公共待办队列与审核员主动认领；
- 管理员重新分派；
- 商品差异、PO 冲突和币种冲突的逐项处理；
- 审核员提交批准申请或作废申请；
- 管理员批准、退回或作废；
- 追加式审计记录；
- 乐观并发控制；
- Case 列表、详情、处理和审批界面；
- 对应 API、迁移、领域服务、仓储、文档和测试。

### 不包含

- 补充材料附件上传；
- 邮件、短信或第三方通知；
- SLA、时效统计、处理量报表；
- 自动排班或负载均衡分派；
- 新增 `approver` 角色；
- 修改已经批准的 Invoice/Receive Note Version；
- 重新计算或覆盖历史 Reconciliation；
- 原生 `.xlsx` 导出。

## 核心设计原则

### 计算结果与人工流程分离

现有 Reconciliation 继续表示规则引擎在特定时间、针对特定批准版本生成的不可变
计算快照。人工处理不能修改商品差异、汇总统计或 `requires_review`。

新增的 Reconciliation Case 只表达人工工作流：责任人、异常项处理结论、审批状态
和审计历史。两者通过 `reconciliation_id` 关联。

### 清洁对账不制造人工步骤

当 `requires_review=false` 时，对账结果视为 `cleared`，不创建 Case，也不进入
认领和管理员审批流程。`cleared` 是查询和界面使用的派生展示状态，不是 Case
状态，也不要求给 Reconciliation 增加可变状态字段。结果仍保留、可查询并可导出。

### 终态不可变

`approved` 和 `voided` 是不可变终态。进入终态后不得修改负责人、异常项结论或
Case 状态，只允许查询、审计和导出。

## 角色与权限

### Reviewer

- 查看公共队列、自己的 Case 和其他审核员 Case；
- 认领 `unassigned` Case；
- 只有当前负责人可以修改异常项、提交批准申请或提交作废申请；
- 非负责人只能只读查看。

### Admin

- 查看所有 Case；
- 将非终态 Case 重新分派给 Reviewer；
- 对 `pending_approval` 执行批准或退回；
- 对 `pending_void` 执行作废或退回；
- 管理员不能绕过异常项完整性规则直接批准。

本阶段复用现有 `reviewer` 和 `admin` 两种角色，不新增角色体系。

## 状态模型

Case 状态：

| 状态 | 含义 | 允许的下一状态 |
|---|---|---|
| `unassigned` | 尚无负责人 | `in_progress` |
| `in_progress` | 已认领，负责人处理中 | `pending_approval`、`pending_void` |
| `pending_approval` | 等待管理员批准 | `approved`、`in_progress` |
| `pending_void` | 等待管理员确认作废 | `voided`、`in_progress` |
| `approved` | 差异已被财务接受 | 无 |
| `voided` | 本次对账无效 | 无 |

状态转换规则：

1. Reviewer 认领时，`unassigned → in_progress`。
2. 所有异常项均为 `business_exception` 且备注完整时，负责人可以执行
   `in_progress → pending_approval`。
3. 存在 `document_data_error` 或 `matching_error` 时，负责人只能执行
   `in_progress → pending_void`。
4. 存在 `waiting_for_documents` 或未处理项时，不允许提交任何终态申请。
5. Admin 批准时，`pending_approval → approved`。
6. Admin 确认作废时，`pending_void → voided`。
7. Admin 退回时，必须填写原因，Case 返回 `in_progress`，负责人保持不变。
8. Admin 可以对已有负责人的非终态 Case 重新分派；重新分派不会改变 Case 状态，
   且必须填写原因。`unassigned` Case 仍由 Reviewer 主动认领。

不提供从 `approved` 或 `voided` 恢复的操作。如果业务需要重新核对，应基于正确的
批准版本创建新的 Reconciliation，而不是复活旧 Case。

## 异常项

系统为以下结果创建 Case Item：

- `mismatch` 商品行；
- `invoice_only` 商品行；
- `receive_note_only` 商品行；
- `purchase_order_match=false`；
- `currency_match=false`。

`exact` 和 `within_tolerance` 商品行不会创建必须人工处理的 Item，但仍在详情页的
原始结果区域显示。

每个 Item 的处理类型为：

| 类型 | 业务含义 | 是否允许提交批准 |
|---|---|---|
| `business_exception` | 差异真实存在，但业务允许接受 | 是 |
| `document_data_error` | Invoice 或 Receive Note 数据错误 | 否，只能申请作废 |
| `matching_error` | 选择了错误单据或错误对应关系 | 否，只能申请作废 |
| `waiting_for_documents` | 等待外部补充材料 | 否 |

每次设置处理类型都必须填写非空备注。补充材料本阶段在线下取得；材料到齐后，负责
人更新类型和备注，不在系统中上传附件。

## 数据模型

### `reconciliation_cases`

- `case_id`：UUID 主键；
- `reconciliation_id`：唯一外键，确保一次异常对账只有一个 Case；
- `status`；
- `assignee_user_id`：可空 Reviewer 外键；
- `revision`：从 1 开始的乐观锁版本；
- `created_at`、`claimed_at`、`submitted_at`、`completed_at`；
- `created_by`：系统创建时记录触发该 Reconciliation 的用户。

### `case_items`

- `item_id`：UUID 主键；
- `case_id`：外键；
- `item_type`：`line`、`purchase_order_conflict` 或 `currency_conflict`；
- `line_result_id`：商品行时必填，头部冲突时为空；
- `resolution_type`：可空；
- `resolution_note`：可空；
- `resolved_by`、`resolved_at`：可空；
- `updated_at`。

商品 Item 对同一 `line_result_id` 唯一；每个 Case 的 PO 与币种冲突类型分别唯一。
Item 只引用不可变计算结果，不复制或修改原始差异数值。

### `case_actions`

- `action_id`：UUID 主键；
- `case_id`；
- `item_id`：逐项修改时填写，其余操作为空；
- `actor_user_id`；
- `action`：`created`、`claimed`、`reassigned`、`resolution_changed`、
  `submitted_for_approval`、`submitted_for_void`、`returned`、`approved`、
  `voided`；
- `old_value`、`new_value`：JSON；
- `reason`：退回、重新分派等需要解释时填写；
- `created_at`。

Action 只能插入，不能更新或删除。Case 与 Item 保存当前读模型，Action 保存完整
变更历史，避免每次查询都重放事件。

## 组件边界

### `ReconciliationCaseService`

负责：

- Case 创建和异常项生成；
- 角色、负责人和状态门禁；
- 提交条件校验；
- 乐观并发校验；
- 在同一事务中更新当前状态并追加 Action。

它不重新执行对账规则，也不修改 Document Version 或 Reconciliation。

### `ReconciliationCaseRepository`

负责 Case、Item 和 Action 的原子读写。认领使用条件更新，只有
`status=unassigned AND assignee_user_id IS NULL AND revision=<expected>` 时成功。

### 现有 Reconciliation 服务

现有服务在持久化 Reconciliation 后，根据 `requires_review` 决定是否在同一业务
事务中创建 Case。为避免“有异常结果但没有 Case”的部分成功，Reconciliation 与
Case 创建必须共享事务边界，或由一个上层 Unit of Work 原子提交。

## API

所有接口要求现有 Session 认证。

| 方法 | 路径 | 权限与用途 |
|---|---|---|
| GET | `/api/reconciliation-cases` | Reviewer/Admin；按状态、负责人筛选 |
| GET | `/api/reconciliation-cases/{case_id}` | Reviewer/Admin；详情与历史 |
| POST | `/api/reconciliation-cases/{case_id}/claim` | Reviewer；认领未分派 Case |
| POST | `/api/reconciliation-cases/{case_id}/reassign` | Admin；重新分派 |
| PUT | `/api/reconciliation-cases/{case_id}/items/{item_id}/resolution` | 当前负责人；更新结论 |
| POST | `/api/reconciliation-cases/{case_id}/submit-approval` | 当前负责人；申请批准 |
| POST | `/api/reconciliation-cases/{case_id}/submit-void` | 当前负责人；申请作废 |
| POST | `/api/reconciliation-cases/{case_id}/approve` | Admin；最终批准 |
| POST | `/api/reconciliation-cases/{case_id}/return` | Admin；退回并要求原因 |
| POST | `/api/reconciliation-cases/{case_id}/void` | Admin；最终作废 |

所有改变状态或结论的请求都携带 `expected_revision`。成功响应返回新 revision。

查询列表支持：

- `status`；
- `assignment=unassigned|mine|all`；
- Invoice Number 精确或前缀搜索；
- `page` 从 1 开始，`page_size` 默认为 50 且最大为 100；
- 默认按创建时间升序，使最早待办优先出现。

同一创建时间使用 `case_id` 升序作为稳定的第二排序键。不在本阶段加入任意排序器、
复杂全文搜索或报表查询。

## 前端设计

### Case 队列

在现有导航新增 `Cases`：

- `Unassigned`：公共待认领；
- `My work`：当前用户负责的处理中 Case；
- `Pending approval`：管理员审批队列；
- `Completed`：已批准或作废的只读记录。

列表显示 Invoice Number、Receive Note Numbers、异常数量、状态、负责人和创建时间。

### Case 详情

详情页包含：

1. 不可变对账摘要；
2. 必须处理的异常项；
3. `exact` 与 `within_tolerance` 的只读明细；
4. 当前负责人和可执行操作；
5. 按时间排序的审计历史。

负责人可为每个异常项选择处理类型并填写备注。其他 Reviewer 查看相同页面，但控件
只读。Admin 在待审批状态看到批准、退回或作废操作。

前端按钮是否可见只是可用性提示，所有权限与状态规则必须由后端再次验证。

## 并发与错误处理

- Revision 不一致返回 `409 CASE_REVISION_CONFLICT`，前端提示数据已更新并刷新；
- Case 已被他人认领返回 `409 CASE_ALREADY_CLAIMED`；
- 非负责人修改返回 `403 CASE_ASSIGNEE_REQUIRED`；
- 状态不允许操作返回 `409 CASE_INVALID_TRANSITION`；
- 异常项未完成返回 `409 CASE_ITEMS_INCOMPLETE`；
- 结论类型与提交目标冲突返回 `409 CASE_SUBMISSION_CONFLICT`；
- Case 不存在返回 404；
- 终态修改一律返回 `409 CASE_TERMINAL`。

每个修改操作必须在一个数据库事务中完成：锁定/校验 revision、更新当前读模型、
递增 revision、追加 Action。任一步失败则整体回滚。

## 测试策略

### 领域与服务测试

- 异常结果创建 Case，清洁结果不创建 Case；
- 每种差异生成正确 Item；
- Case 创建时产生 `created` Action；
- 完整状态转换矩阵；
- Reviewer/Admin 权限矩阵；
- 四种处理类型与两种提交目标的组合；
- 未处理、等待材料和缺少备注时禁止提交；
- 终态不可修改；
- 退回后可再次处理和提交；
- 每个动作均产生正确审计记录。

### 仓储与并发测试

- Reconciliation 与 Case 原子创建；
- 两名 Reviewer 同时认领时只有一人成功；
- 旧 revision 不能覆盖新数据；
- Action 只追加；
- 事务异常时状态和 Action 同时回滚。

### API 测试

- 未登录、Reviewer 和 Admin 的权限行为；
- 404、403、409 错误码和稳定错误 code；
- 筛选、分页和默认顺序；
- 请求与响应 Schema。

### 前端测试

- 队列分组与空状态；
- 负责人和只读权限表现；
- 处理类型控制提交按钮；
- revision 冲突后的刷新提示；
- 管理员批准、退回和作废操作。

### 回归验证

- 现有对账计算结果保持不变；
- 现有上传、抽取、审核、批准和 CSV 导出测试全部通过；
- 数据库迁移可在空库和已有阶段 1 数据库上执行；
- 文档同步检查和前端生产构建通过。

## 验收场景

### 业务允许差异并批准

1. 创建含数量差异的 Reconciliation，系统生成 `unassigned` Case；
2. Reviewer A 认领；Reviewer B 只能查看；
3. Reviewer A 将全部异常项标记为 `business_exception` 并填写备注；
4. Reviewer A 提交批准；
5. Admin 批准；
6. Case 成为不可变 `approved`，历史完整可查。

### 单据错误并作废

1. Reviewer 将一个 Item 标记为 `document_data_error`；
2. 系统拒绝提交批准，但允许提交作废；
3. Admin 确认作废；
4. Case 成为不可变 `voided`；正确单据需重新批准并创建新的 Reconciliation。

### 等待材料与退回

1. Reviewer 标记 `waiting_for_documents`，系统禁止提交；
2. 材料在线下到齐后，Reviewer 更新为 `business_exception`；
3. Admin 审批时填写原因并退回；
4. Case 回到 `in_progress`，Reviewer 修改后再次提交；
5. 所有轮次均保留在 Action 历史中。

### 并发认领

1. 两名 Reviewer 同时打开同一 `unassigned` Case；
2. 第一笔认领成功并递增 revision；
3. 第二笔返回 `CASE_ALREADY_CLAIMED` 或 `CASE_REVISION_CONFLICT`；
4. 不产生双负责人或丢失更新。
