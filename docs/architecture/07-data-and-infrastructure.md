# 数据模型与基础设施

## 数据为什么要分 PostgreSQL 与 MinIO

项目同时处理两类数据：

- 适合查询、关联、事务和审计的结构化状态；
- 体积较大、主要按对象读取的二进制原件和解析产物。

因此：

| 存储 | 保存内容 |
|---|---|
| PostgreSQL | Task、Run、解析文本、Draft、Evidence、Issue、Version、Action、Session、Reconciliation、Case/Item/Case Action |
| MinIO | 原始 PDF/图片、MinerU ZIP 产物 |

MongoDB 和 Milvus 当前都不是发票核对链路的依赖。

## 核心实体关系

```mermaid
%%{init: {'flowchart': {'htmlLabels': true, 'nodeSpacing': 40, 'rankSpacing': 30}}}%%
flowchart TD
    T["Task"] --> R["Run"]
    R --> P["Parse Result"]
    R --> D["Draft"]
    D --> E["Evidence"]
    D --> I["Issues"]
    D --> V["Versions"]
    V --> A["Actions"]
    V --> C["Reconciliation"]
```

### 关系解释

- 一个 Task 可以多次 Run；
- 一个成功 Run 对应一份 ParseResult 和 Draft；
- Draft 拥有多条 Evidence 和 Issue；
- 一个 Task 可以产生多个 Version；
- 每个 Version 有多条 Review Action；
- 一次 Reconciliation 引用一个 Invoice Version 和多个 Receive Note Version。
- 只有异常 Reconciliation 拥有唯一的 Reconciliation Case；Case 再拥有多条
  Case Item 和只追加的 Case Action。

## 为什么解析 Markdown 存 PostgreSQL，ZIP 存 MinIO

Worker 归一化时频繁读取 Markdown、blocks 和 tables，它们适合按 Run 快速查询；
完整 ZIP 是审计/调试产物，体积更大且无需关系查询，因此放 MinIO。

生产环境中如果 Markdown 极大，可考虑把完整产物放对象存储，只在数据库保存
摘要和对象键。当前 Pilot 优先简化读取链路。

## MinIO 对象键

原件：

```text
<document_type>/<task_id>/original/<safe_filename>
```

MinerU 产物：

```text
<document_type>/<task_id>/runs/<run_id>/mineru/result.zip
```

Task/Run ID 使不同项目、不同上传和不同尝试不会覆盖彼此。

## 文件上传安全边界

`DocumentUploadService` 不信任浏览器上报的 MIME：

1. 限制文件大小；
2. 清理文件名并移除路径；
3. 根据 Magic Bytes 识别 PDF/PNG/JPEG；
4. 检查扩展名与真实格式一致；
5. 计算 SHA-256；
6. 先写 MinIO，再写 PostgreSQL；
7. 数据库创建失败时删除刚写入的对象。

这不是完整恶意文件扫描。生产环境仍需杀毒、内容隔离和下载响应头策略。

## PostgreSQL 为什么适合这个项目

核心数据具有明显关系：

- Version 引用 Task 和 Draft；
- Action 引用 Version 和 User；
- Reconciliation 引用多个批准版本；
- 状态领取需要条件更新；
- 审核和不可变约束需要事务。

PostgreSQL 相比 MongoDB 的主要优势不是“更高级”，而是关系、约束、事务和
条件更新更符合此业务。

## Reconciliation 与 Case 的数据边界

`reconciliations.result_json` 和 `reconciliation_line_results` 保存规则引擎生成的
不可变计算快照。人工处置不会改写数量、金额、匹配状态或 `requires_review`；
`reconciliation_cases`、`case_items` 和 `case_actions` 单独保存负责人、处理结论、
流程状态和审计历史。清洁结果不创建 Case，`cleared` 只是读取时的展示含义。

`ReconciliationApplicationService.compare` 在计算结果后先生成稳定的行结果 ID，
再由纯 Factory 为异常结果生成 Case、Item 和初始 `created` Action。
`PostgresReconciliationRepository.create` 使用同一个 Session 依次写入 Reconciliation、
Receive Note 关联、行结果和可选 Case 聚合。因为这些 Row 没有 ORM relationship，
Repository 会在外键父子层之间显式 flush 以固定真实数据库的插入顺序，但最后仍只
提交一次。因此任一 Case Item 或 Action 写入失败时，Reconciliation 也会一起回滚，
不会留下“有异常、无待办”的部分成功状态。

## Case 并发与不可变保护

- `reconciliation_cases` 对 `reconciliation_id` 唯一，保证一个异常快照最多一个 Case；
- `revision` 从 1 开始，每次写操作都携带 `expected_revision`；Repository 用
  `case_id + revision` 条件更新，未命中时返回 `CASE_REVISION_CONFLICT`；
- 认领还要求 Case 仍为 `unassigned` 且没有负责人，因此并发认领只有一个提交者
  能获得负责人身份；
- 每次成功变更在同一事务更新 Case/Item、递增 revision，并追加恰好一条 Action；
- `case_actions` 的 PostgreSQL 触发器拒绝 UPDATE/DELETE；Case 进入 `approved` 或
  `voided` 后，Case 与其 Item 的触发器都拒绝 UPDATE/DELETE。Item 触发器在检查
  父 Case 时加行锁，避免终态转换与 Item 更新竞态穿透。

服务层仍是权限和状态机的第一道边界：只有当前负责人 Reviewer 能编辑和提交，
Admin 负责重新分派与最终决定。数据库触发器用于阻止绕过服务的终态或审计篡改，
不能替代服务层规则。终态不提供恢复；需要纠正时必须批准正确的新单据版本并创建
新的 Reconciliation。

## Worker 租约

`claim_next()` 不是简单读取第一条 queued 记录。Repository 必须原子地声明：

> 这个 Run 在租约过期前由当前 Worker 处理。

这样可以减少两个 Worker 同时领取同一任务的概率。当前 Pilot 没有实现完整
fencing token 和租约续期，因此不能宣称支持可靠的多 Worker 并发。

## Worker 心跳

Worker 定期向 `worker_heartbeats` 写入：

- worker_id；
- version；
- started_at；
- last_seen_at。

Runtime API 根据 `last_seen_at` 是否超过阈值判断 online/offline。它用于解释
排队状态，不是完整监控系统。

## 迁移顺序

`migrations/versions` 记录 Schema 演进：

1. extraction tasks；
2. extraction runs；
3. parse results 和租约；
4. drafts/evidence/issues；
5. users/sessions；
6. document versions/reviews；
7. reconciliation records；
8. worker heartbeats；
9. cancellation；
10. model provenance；
11. reconciliation cases、case items、case actions 与不可变触发器。

这组迁移本身反映了项目的设计演进：先建立文件与任务，再增加 AI 解析、
人工治理、核对和可观测性。

## 环境隔离

即使与其他项目复用同一 PostgreSQL/MinIO 服务器，也必须分离：

- PostgreSQL database：`ivida_invoice_reconciliation`；
- MinIO bucket：`ivida-invoice-documents`；
- API 端口：8200；
- 前端端口：5274。

“连接同一台服务器”不等于“共享同一份业务数据”。

## 面试复习点

- PostgreSQL 保存关系和审计状态，MinIO 保存二进制对象；
- Task/Run/Draft/Version 的外键关系表达业务生命周期；
- Reconciliation 计算快照与 Case 人工流程分表，避免人工操作污染确定性结果；
- 单事务创建、条件 revision 更新和追加式 Action 分别解决部分成功、丢失更新和审计覆盖；
- Magic Bytes 比浏览器 MIME 更可信；
- 租约与心跳解决不同问题：前者防重复领取，后者说明 Worker 是否活着；
- 当前单 Worker Pilot 不应包装成高可用平台。
