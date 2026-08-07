# 重复发票识别与门店范围设计

## 1. 背景与目标

当前系统已经支持外部 Invoice/Receive Note 上传、结构化抽取、人工审核、不可变
批准版本、Taptouch Receiving 导入、tenant/store 范围的机器凭据以及确定性对账。
下一阶段优先降低重复付款风险，而不是继续扩展基础设施能力。

本阶段交付一个完整业务闭环：

1. 新上传单据必须属于明确的 tenant/store；
2. 同一门店的完全相同文件不重复创建 Task 或 MinIO 原件；
3. 结构化 Invoice 使用可解释的确定性规则发现疑似重复；
4. Reviewer 必须在批准前记录重复处置结论和原因；
5. 所有门店访问、检测、处置和批准都保留可审计边界。

本设计以 IVIDA/Taptouch 业务为准。Zeemart 只提供产品交互参考，不作为数据契约
或流程事实来源。

## 2. 已确认的产品决策

- 完全重复直接阻止新建；疑似重复交由人工确认。
- 采用两阶段检测：上传时检查文件 Hash，结构化审核时检查业务字段。
- 所有新上传的 Invoice 和外部 Receive Note 都必须选择 tenant/store。
- 建立轻量 Tenant/Store 注册表，不在本项目重做完整门店主数据系统。
- Reviewer 只能访问被分配的 Store；Admin 可以跨门店管理。
- 疑似重复必须选择 `confirmed_duplicate`、`confirmed_distinct` 或
  `replacement`，并填写原因。
- 相同文件重放返回原 Task；失败 Task 在原 Task 重试，取消 Task 先恢复。
- 疑似检测只使用可解释的确定性规则，不让 LLM 自动裁决。
- 候选包括同门店已批准 Invoice 和活跃审核中的 Invoice；排除失败、取消和拒绝。
- 更正/替代只建立审计关系，不自动删除、作废或改写旧 Version。
- 交付范围必须覆盖上传、审核、处置、批准、权限和审计的完整前后端闭环。

## 3. 范围与非目标

### 3.1 本阶段范围

- Tenant、Store 轻量注册与启停；
- 用户 Store Scope 分配；
- 新上传文档的 Store 归属；
- Store 范围的 SHA-256 幂等；
- Invoice 疑似重复规则与证据；
- Duplicate Assessment 生命周期；
- 审核页处置和批准门禁；
- 更正/替代 Version 关系；
- 全链路 Store 数据隔离；
- 历史未归属数据的安全迁移策略；
- API、数据库、前端和 PostgreSQL 集成测试。

### 3.2 明确不做

- LLM 或向量模型自动裁决重复；
- 自动删除、合并、作废或覆盖旧发票；
- 完整供应商主数据与供应商自动合并；
- PO 创建、付款、银行连接或会计入账；
- 通用财务风险规则平台；
- 根据文件内容自动猜测历史文档门店；
- 批量重复发票报表；
- 可靠事件交付、死信和补数。

## 4. 总体架构

新增三个独立边界，避免把重复逻辑塞入现有 Task 或不可变 Version 状态机。

### 4.1 门店范围基础

Tenant/Store 注册表保存内部 ID、外部 Taptouch ID、展示名称和启用状态。
用户通过 Store Scope 获得访问范围。Admin 管理注册表和分配关系，Reviewer 只操作
被授权门店。

所有新上传文档都必须关联有效 Store。Taptouch Receiving 仍保留外部 tenant/store
审计字段，同时解析到内部 Store FK，使上传路径与结构化集成路径共享同一权限边界。

### 4.2 上传幂等

完全重复属于文件身份问题，不属于人工 Duplicate Assessment。上传服务在写入 Task
前，以 `store_id + document_type + sha256` 检查已有原件。重放返回已有 Task，不创建
第二个 Task、Run 或业务版本。

### 4.3 Duplicate Assessment

疑似重复属于可变调查工作流。Assessment 保存当前 Invoice、检测指纹、候选、规则
证据、revision 和处置动作。Invoice Version 继续保持不可变；批准门禁只读取最新
Assessment 是否与当前字段和候选集合一致。

## 5. 数据模型

以下名称表达稳定职责；实施计划可以按照现有 SQLAlchemy/Alembic 命名规范做机械
调整，但不得改变关系和约束语义。

### 5.1 门店与权限

`business_tenants`：

- 内部 tenant ID；
- external tenant ID；
- display name；
- active；
- created/updated audit fields。

`business_stores`：

- 内部 store ID；
- tenant FK；
- external store ID；
- display name；
- active；
- created/updated audit fields。

`user_store_scopes`：

- user FK；
- store FK；
- granted by；
- granted at；
- `(user_id, store_id)` 唯一。

外部 tenant ID 全局唯一；external store ID 在 tenant 内唯一。停用记录不能物理
删除，因为历史文档仍引用它。

### 5.2 Task 与 Version 范围

`extraction_tasks` 和 `document_versions` 增加内部 `store_id` 与明确的 scope 状态。

- 新数据必须为 `known` 并关联有效 Store；
- 历史无法可靠归属的数据迁移为 `legacy_unknown`；
- `known` 当且仅当 `store_id` 非空；
- 普通 Reviewer 不读取 `legacy_unknown`；
- Admin 可以通过追加式历史 Scope Assignment 为旧数据补录 Store；
- Version 复制 Task 的 Store，不依赖以后可能改变的 UI 上下文。

新 Version 直接保存 `store_id`。已经 Approved 的历史 Version 不能为了补录门店而
UPDATE；其有效 Scope 通过独立的 `legacy_document_scope_assignments` 解析。Assignment
保存目标 Task/Version、Store、操作者、原因、时间及可选 supersedes 关系，保持追加式
审计。普通新业务不得使用这张表代替正常 Store FK。

Taptouch Version 必须解析到注册 Store，同时继续保存 source system、external tenant、
external store、external receiving ID 和 upstream version。

### 5.3 完全重复唯一性

文件身份独立保存到 `document_file_identities`：

- task FK，且一个 Task 最多一个当前文件身份；
- store FK；
- document type；
- sha256；
- created at。

对文件身份强制：

```text
store_id + document_type + sha256
```

唯一。失败、取消和 duplicate 终态仍占据文件身份。新上传在创建 Task 的同一事务中
创建身份。`legacy_unknown` 初始没有身份；Admin 补录 Scope 时必须同时插入身份，
因此补录也不能绕过同 Store Hash 唯一约束。

### 5.4 Duplicate Assessment

`duplicate_assessments`：

- assessment ID；
- subject task ID；
- detection revision；
- subject fingerprint；
- status：`pending`、`resolved`、`superseded`；
- resolution：`confirmed_duplicate`、`confirmed_distinct`、`replacement` 或空；
- expected/current revision；
- created/resolved timestamps。

每个 subject task 同时最多存在一个未 supersede 的当前 Assessment。

`duplicate_candidates`：

- assessment FK；
- candidate task FK；
- candidate version FK，可空；
- matched rule；
- evidence snapshot；
- candidate lifecycle snapshot；
- `(assessment_id, candidate_task_id)` 唯一。

`duplicate_actions` 为只追加审计：

- assessment FK；
- actor user FK；
- action；
- previous/new status；
- resolution；
- reason；
- created at。

`invoice_relationships`：

- newer approved version FK；
- prior approved version FK；
- relationship type=`replacement`；
- source assessment/action；
- created by/at；
- 新旧 Version 不能相同，关系不得重复。

## 6. 业务流程

### 6.1 管理准备

Admin 注册 Tenant/Store、启用门店并为 Reviewer 分配 Store Scope。未注册或停用门店
不能接收新上传、Taptouch 导入或新对账。

### 6.2 上传

1. 用户选择自己有权访问的 Store；
2. 服务验证文件类型、Magic Bytes、大小和文件名；
3. 计算 SHA-256，但尚未产生第二个业务身份；
4. 查询同 Store、同文档类型和 Hash；
5. 首次上传写入 MinIO 并创建 Task，返回 `201 created=true`；
6. 重放返回 `200 created=false` 和已有 Task；
7. 前端提示文件已存在并打开原 Task。

失败 Task 可由该 Store 的 Reviewer/Admin 沿原 Task 重试。取消 Task 只能由 Admin
恢复后处理。重放本身不能绕过恢复权限或自动改变 Task 状态。

### 6.3 抽取与初次检测

新 Task 沿现有 MinerU、Normalization 和人工审核链路处理。Invoice Draft 达到可审核
状态后执行疑似重复检测。没有候选时不制造 Assessment 待办；有候选时保存当前字段
指纹、候选集合和证据快照。

### 6.4 人工处置

审核页展示候选发票及每条命中信号。Reviewer 必须填写原因并选择：

- `confirmed_duplicate`：当前审核在一个事务中以 duplicate 终态结束，不生成
  Approved Version；
- `confirmed_distinct`：允许当前 Invoice 继续批准；
- `replacement`：必须选择一个已批准候选，允许批准新 Version，并在同一事务建立
  新旧 Version 关系。

### 6.5 批准前复检

批准前重新计算检测输入。若关键字段、候选集合、候选生命周期或 Assessment revision
发生变化，旧处置失效并生成新 revision。Reviewer 必须基于最新证据重新确认。

## 7. 确定性检测规则

### 7.1 检测范围

- 同一 tenant/store；
- document type 为 Invoice；
- 候选为已批准 Version 或活跃审核 Task；
- 排除当前 Task；
- 排除失败、取消、duplicate 和拒绝记录；
- `legacy_unknown` 不参与 Store 范围检测。

### 7.2 归一化

供应商身份优先使用 business number。缺失时，供应商名称统一大小写、去除首尾空白并
合并连续空白；不通过 LLM 或模糊知识自动合并不同供应商。

发票号统一大小写，仅移除 Unicode 空白以及 `-`、`_`、`/`、反斜杠和 `.`，保留其余
字母、数字及顺序。币种统一为大写，金额使用现有 Decimal 语义，不用浮点近似。

### 7.3 触发规则

强规则：

- 供应商身份一致；
- 归一化发票号完全一致。

标准规则：

- 归一化供应商名称一致；
- 归一化发票号一致；
- 币种一致；
- 总额一致。

相似规则：

- 供应商身份一致；
- 币种与总额一致；
- Invoice 日期相差不超过 30 天；
- 两个归一化发票号长度都至少为 6，并且 Levenshtein 距离等于 1；只计单字符增加、
  删除或替换，字符交换不单独视为一次变化。

单独金额相同、PO 相同、税额相同或商品行相似不能触发 Assessment，只能作为辅助
证据。缺少规则必需字段时不猜测，也不触发该规则。

关键字段包括供应商身份、发票号、日期、币种和总额。任一字段修改都会改变 subject
fingerprint，并使旧检测结论失效。

## 8. 权限与数据隔离

- Reviewer 只能列出和操作自己 Store Scope 内的 Task、Draft、Version、Assessment、
  Reconciliation 和 Case；
- Admin 可以跨门店管理，并处理 `legacy_unknown`；
- 直接访问其他门店对象返回 404，避免泄露对象存在性；
- 主动选择无权限 Store 上传返回 403 `store_scope_forbidden`；
- 后端所有查询强制 Scope，前端筛选不是安全边界；
- Candidate Matching 与 Reconciliation 必须要求 Invoice 和 Receive Note 属于同一
  Store；
- Taptouch 机器凭据的 external tenant/store 范围与内部 Store 注册必须同时通过。

## 9. API 与页面行为

### 9.1 Admin

提供 Tenant/Store 的查询、创建、启停，以及用户 Store Scope 分配。停用操作保留历史
引用，不做级联删除。

### 9.2 上传

上传请求新增必填 `store_id`。响应明确 `created`，重放返回已有 Task。无权限返回
403；Store 不存在或停用返回稳定业务错误。

### 9.3 审核

审核详情返回当前 Assessment、候选、匹配规则和字段证据。处置接口要求：

- resolution；
- reason；
- expected assessment revision；
- replacement 时的 prior approved version。

审核页存在未处置或 stale Assessment 时禁用批准。终态后处置和关系只读。

### 9.4 稳定错误码

- `store_scope_forbidden`；
- `store_not_registered`；
- `store_inactive`；
- `duplicate_assessment_required`；
- `duplicate_assessment_stale`；
- `duplicate_assessment_revision_conflict`；
- `replacement_candidate_not_approved`。

## 10. 事务与并发

### 10.1 上传竞争

两个并发请求可能同时未读到已有 Task，并分别写入自己的对象键。数据库唯一约束只
允许一个 Task 提交。失败方回滚数据库、删除自己写入的 MinIO 对象，再查询并返回
胜出的 Task。补偿删除失败时记录 orphan object 告警事实，但不创建第二个 Task。

### 10.2 Assessment 竞争

处置必须携带 expected revision。未命中条件更新时区分 stale 与 revision conflict，
前端重新加载，不覆盖其他 Reviewer 的动作。

### 10.3 批准原子性

批准前锁定当前审核状态并复检。以下事实必须在同一事务完成：

- distinct：批准 Version 与 Duplicate Action；
- replacement：批准 Version、Version Relationship 与 Duplicate Action；
- duplicate：拒绝当前审核、Task duplicate 终态与 Duplicate Action。

任一步失败全部回滚，不允许出现已批准但没有处置审计，或已建立 replacement 关系但
新 Version 未批准。

### 10.4 Store 状态竞争

上传、Taptouch 导入或对账创建必须在事务边界再次确认 Store 仍启用。并发停用导致
业务操作返回 409，不留下部分数据。

## 11. 历史数据迁移

现有上传 Task/Version 没有可靠 tenant/store 来源，因此统一迁移为
`legacy_unknown`，不根据文件名、供应商、PO 或已有 Receiving 自动推断，也不修改
已经 Approved 的不可变 Version。

Admin 补录历史 Store 时：

1. 验证目标 Store；
2. 检查用户权限；
3. 检查目标 Store 下 Hash 唯一性；
4. 对 Invoice 运行疑似重复检测；
5. 原子创建 `legacy_document_scope_assignments`、文件身份和管理审计；未批准 Task 可
   同步写入直接 Store FK，Approved Version 保持原样。

发生完全重复冲突时拒绝补录，并指向已有 Task；不能通过历史补录绕过上传幂等。

## 12. 错误处理与可观测性

业务错误返回稳定 code 和不含秘密的说明。日志可以记录 user/principal、store、task、
assessment、rule 和错误码，不记录 Bearer Token、Session Token、原始文件正文或完整
财务 Payload。

以下情况必须 fail closed：

- Scope 配置缺失或用户无门店权限；
- Store 未注册或停用；
- Assessment revision 不一致；
- replacement 候选不是已批准 Version；
- 批准前候选或关键字段已变化；
- 数据库唯一约束或不可变约束失败。

## 13. 测试与验收

### 13.1 测试分层

- 领域测试：归一化、三档规则、缺失字段和边界日期；
- 服务测试：Hash 重放、Assessment 生命周期、处置与批准门禁；
- API 测试：Store Scope、403/404、稳定错误码和 revision；
- PostgreSQL 集成测试：唯一约束、并发、事务回滚和只追加审计；
- MinIO 补偿测试：只删除失败请求自己的对象；
- 前端测试：Store 选择、重放跳转、候选证据、处置和按钮状态；
- 迁移测试：`legacy_unknown`、升级、降级和再次升级。

### 13.2 必须通过的验收场景

1. 同一 Store 同一文件上传两次，只存在一个 Task 和一个原件；
2. 不同 Store 上传同一文件可以分别创建 Task；
3. 失败或取消 Task 重放时返回原 Task；
4. 已批准或活跃审核中的相似 Invoice 生成可解释候选；
5. 失败、取消、duplicate、拒绝、其他 Store 或 legacy unknown 不生成候选；
6. 修改关键字段使旧处置失效；
7. confirmed duplicate 不产生 Approved Version；
8. confirmed distinct 可以批准并保留原因；
9. replacement 建立新旧 Version 关系且不改写旧 Version；
10. 无权限用户无法通过列表、直接 URL、候选或对账发现其他 Store 数据；
11. 未注册或停用 Store 不能接收新上传、Taptouch 导入或新对账；
12. CI 在真实 PostgreSQL 完成迁移升级、降级和再次升级。

## 14. 成功标准与后续顺序

本阶段成功意味着重复风险在上传和审批两个入口都被控制，并且不会牺牲不可变版本、
门店隔离或人工审计。成功不以页面数量或规则数量衡量。

完成后，下一独立阶段才考虑可靠事件交付、重试退避、事件追踪、死信、告警与批量
补数。部分收货分配仍需真实业务样本证明必要性后再设计。
