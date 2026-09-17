# 02 架构与数据契约

## 1. 固定架构

现有 React＋FastAPI 模块化单体、PostgreSQL、MinIO、MinerU、OpenAI-compatible normalizer 保留。增加一个 workspace 后台进程，仍使用同一数据库，无 Redis/Celery/Kafka。业务逻辑是确定性 Python；此处开发 Agent 的 Harness 与产品内模型调用是两回事。

调用方向：

```text
WorkspacePage / DocumentPage
  → workspaceClient → /api/workspace → WorkspaceService
    → WorkspaceRepository（原子用例）
    → matching / comparison（纯函数）

上传 → prepare_upload（验证和对象存储）
     → Repository 原子创建原 Task＋Run＋workspace Document
     → 原 ExtractionWorker → 原 Draft/Evidence

WorkspaceWorker（每 3 秒）
  → Repository 同步最新 Draft 与上游版本
  → 重建未完成发票预览 → Repository 条件保存
```

domain 不导入 infra/API；rules 不访问 DB/网络；service 依赖 ports；API 只负责输入、身份、HTTP；worker 不依赖 FastAPI；新 infra 可复用现有 ORM 行，不调用会自行 commit 的旧 Repository 来组成事务。

## 2. 模块文件（不得增删或换名）

```text
app/domain/workspace.py                 全部新 DTO/枚举/错误定义
app/services/workspace_ports.py         全部新 Protocol
app/services/workspace_matching.py      确定性匹配
app/services/workspace_comparison.py    完整性/维度比对
app/services/workspace_service.py       用户操作编排
app/infra/postgres_workspace_repository.py  唯一新持久化实现
app/workers/workspace_worker.py         自动同步与预览
app/api/workspace_routes.py             唯一新业务路由
run_workspace_worker.py                 进程入口
frontend/src/workspace/workspaceTypes.ts
frontend/src/workspace/workspaceClient.ts
frontend/src/workspace/workspacePresentation.ts
frontend/src/workspace/WorkspacePage.tsx
frontend/src/workspace/DocumentPage.tsx
```

现有 database_models.py 增加表；Settings/dependencies/main 接线；不创建第二个数据库 Base、不新建通用 utils/manager/engine 目录、不改变依赖包。不复用旧 Case 状态机冒充简化流程；旧 Case/Version/Reconciliation 仅历史读取。

新快照使用独立 ws 表，是明确的迁移边界：旧历史保留原含义，新工作台使用一次确认模型，不将机器草稿写成旧 approved。旧提取与评测仍可独立使用；新人工修订不自动进入旧 Gold 反馈，后续需要单独 Spec。

## 3. 通用类型约束

ID 为 UUID 字符串；时刻为 UTC ISO-8601；金额和数量以十进制字符串返回，内部 Decimal；禁止 float 财务计算。JSON DTO `extra=forbid`。业务正文 `document` 使用 Invoice/ReceiveNote Schema。`Party.name` 为 nullable；当 ABN 或地址有原文依据但名称缺失时保留部分 Party，禁止用单据标题伪造名称。

`WorkspaceDocument`：

| 字段 | 类型/约束 |
|---|---|
| document_id | UUID PK |
| tenant_id, store_id | 非空 text，部署配置决定，浏览器不得提交 |
| document_type | invoice / receive_note |
| source_kind | upload / taptouch |
| task_id | nullable，upload 必填，UNIQUE；FK extraction_tasks |
| upstream_identity | nullable text，taptouch 必填；`source_system/tenant/store/receiving_id` 的 canonical JSON 数组文本，不能用可能冲突的简单拼接 |
| current_revision_id | nullable UUID；处理完后必填 |
| revision | integer >=1；任何会影响用户操作的变更递增 |
| processing_status | 01 中枚举 |
| review_status | invoice 必填，receive_note null |
| selected_document_ids | UUID[] 去重、排序；invoice 使用 |
| selection_origin | automatic/manual/null |
| selection_note | text/null，manual 1..2000 |
| match_status | 01 中枚举 |
| current_preview_id | UUID/null |
| preview_stale | bool，输入变动后立即置 true |
| current_confirmation_id | UUID/null |
| source_changed | bool，完成后上游变化提醒 |
| error_code | nullable text，稳定系统错误码；成功同步后清空 |
| created_by, created_at, updated_at | created_by nullable UUID FK admin_users；机器导入 null；时间非空 UTC |

`WorkspaceRevision`（追加式）：revision_id、document_id FK、sequence integer、source_draft_id nullable FK、source_version_id nullable FK document_versions、payload（现有业务 JSON）、evidence（原 FieldEvidence[]）、validation_issues（原 ValidationIssue[]）、content_sha256、origin=extracted/manual/upstream、actor_id nullable、reason nullable、created_at。UNIQUE(document_id,sequence)；不允许 update/delete。新 revision 保留机器 evidence 原样，并明确 evidence_origin_revision_id（nullable、自 FK）；人工改动不伪造新原文证据。

`WorkspacePreview`（追加式）：preview_id、invoice_document_id、input_revision_ids（invoice 在首，其余 document_id 排序）、scope_generation bigint、selection_origin、rule_version=`ir-simple-rules-1`、tolerances={quantity:"0",unit_price:"0.01",amount:"0.02"}、input_sha256、result（03 DTO）、created_at。没有 created_by/approved 字段；它不代表批准。相同 invoice+input_sha256+rule_version UNIQUE；input_sha256 包含有序输入、所选关联、容差、scope_generation。

`WorkspaceConfirmation`（追加式）：confirmation_id、invoice_document_id、preview_id FK、invoice_revision_id FK、receive_revision_ids UUID[]、result_snapshot（完整 PreviewResult）、rule_version、tolerances、input_sha256、actor_id FK admin_users、resolution=matched/resolved_with_note、note nullable 1..2000、acknowledged_unverified_dimensions string[]、created_at。不变更旧快照，作废/重开记录在 Action。

`WorkspaceClaim`：receive_document_id PK/FK、invoice_document_id FK、confirmation_id FK、created_at；代表**整张**收货单占用，不是认领人。用户不看见“claim”词。确认时插入，重开时删除；状态变化与 Action 同事务。禁止跨不同发票重复占用。部分分配不支持，返回固定错误，不能擅自实现拆行。

`WorkspaceAction`（追加式）：action_id、document_id、actor_id nullable、action=uploaded/extracted/edited/selection_changed/investigating/confirmed/reopened/voided/source_updated/retry_requested、reason nullable、old_revision nullable int、new_revision int、confirmation_id nullable、created_at。

`WorkspaceScope`：scope_id 固定 tenant/store canonical JSON 文本 PK、generation bigint>=0、last_sync_at UTC/null、last_error_code null、updated_at。全局变更代次用于防止晚到单据下确认旧预览。

`WorkspaceRequest`：scope_id、actor_id、idempotency_key UUID、request_hash、response_status int、response_json、created_at；PK(scope_id,actor_id,idempotency_key)。记录仅成功变更结果，不缓存 4xx/5xx；保留不自动清理。

共八张表，前缀 `ws_`。名称依次 documents/revisions/previews/confirmations/claims/actions/scopes/requests；不得另加业务表。DTO 的 legacy_used、display_status、source_url_available、already_used 为查询派生，不新增列。WorkspaceScopeKey 与 Scope 表的 scope_id 使用同一 canonical JSON 编码。

PostgreSQL 映射固定：UUID字符串用 Text，字符串和枚举用 Text＋CHECK（禁止未列状态），int用Integer、generation用BigInteger、bool用Boolean、UTC用DateTime(timezone=True)、列表和结构化对象用JSONB。所有 *_id 明确目标已给出的均建FK，列表ID由事务内验证，不假装有数组元素FK。current_revision_id/current_preview_id/current_confirmation_id 的循环FK使用 DEFERRABLE INITIALLY DEFERRED；所有历史引用 ON DELETE RESTRICT。生成UUID与created_at由应用提供，数据库不自动推测。

## 4. 数据库实现与一致性

迁移 `20260916_15_workspace.py`，revision=`20260916_15`，down_revision=`20260807_14`。索引：documents(scope,document_type,processing_status,updated_at,document_id)、documents(scope,upstream_identity) UNIQUE WHERE upstream_identity IS NOT NULL、revisions(document_id,sequence) UNIQUE、actions(document_id,created_at,action_id)、previews(invoice_document_id,created_at)。JSON 用 JSONB；表中 ID 与现有模型的 text UUID 存储风格一致。

全 workspace 写操作先获取 `pg_advisory_xact_lock(hashtextextended(scope_id,0))`，再锁 document 行；多 document 按 ID 排序锁。单店低并发下明确接受串行写入，禁止 Agent 换队列或细分锁。事务内不得 OCR、模型调用、MinIO HTTP 或 sleep。确认、编辑、同步、重开使用同样锁顺序。

原上游接入写 Repository 在持久化相关 tenant/store 版本前获取同一 scope advisory lock；确认事务读取原上游最新版本，检查草稿源最新 run/draft，不能只信任稍早的 workspace 投影。失败返回 PREVIEW_STALE，并标记重算。

正式确认必须同事务完成：校验 expected_revision/preview/current source → 重算规则核对 hash → 检查 claims → 写 confirmation＋claims＋action → 更新 document completed/revision → 写幂等响应。任何失败全部回滚。

编辑源单据使所有引用它的未完成发票 preview_stale=true，revision 递增；已完成发票只 source_changed=true，不改结果。新 ready/voided source 到达时 scope.generation++，所有未完成发票失效。确认可保守拒绝因同店无关新单据造成的旧预览，不允许为了少刷新而跳过校验。

## 5. 自动同步与恢复

- workspace Worker 单进程每 3 秒执行 tick；允许第二进程启动但必须通过 scope advisory lock 串行，不重复落数据。
- 上传请求在 MinIO 写成功后，使用 PreparedUpload 元数据单事务创建原 ExtractionTask、原 queued ExtractionRun、ws_document、uploaded action、幂等响应。返回前任务已经持久化排队。SQL 失败时原件可能成为孤儿，尽力删除**本次新建对象**；禁止按前缀批量删除。重复请求先查幂等，禁止重复对象写入。
- Worker 扫描 ws_document 对应 task 的最新 Run/Draft，不扫描所有旧上传任务。不同步非本工作台上传；避免把旧财务历史重新开单。
- upstream 扫描配置门店的最新版本；首次启用也同步已有 active 收货；voided 记录可更新已知文档但不创建可匹配新候选。通过 source_version_id 唯一性和内容 hash 幂等，不能每 tick 生成 revision。
- 本地存在人工修订后，抽取重试不自动覆盖：返回 SOURCE_REVIEW_REQUIRED，保留人工版本；仅失败且未形成 ready revision 的文件允许用户 retry。
- Tick 内分三步：短事务同步源并标失效；锁外以快照纯计算；短事务核验 scope_generation/input revisions 后存预览。并发改变时放弃结果，下 tick 重算。
- 每 tick 最多处理 100 个失效发票，按 updated_at/document_id 升序；单据失败记录稳定 error_code，继续其他单据，不整体卡死。
- 重启通过持久化 stale 标识恢复，无进程内唯一状态；后台停止时前端显示“自动核对服务暂不可用”，不是“没有匹配记录”。

## 6. 旧功能兼容

保留现有历史表、查询、CSV 和 admin Lab；不删除迁移。新记录不调用旧 ReconciliationApplicationService 或 CaseFactory，不进入旧认领审批。

默认 `WORKSPACE_ENABLED=false`，通过验收后负责人设 true。true 时旧 review 写接口、旧 POST /api/reconciliations、旧 Case 变更接口、旧上传/排队入口对浏览器返回 409 LEGACY_READ_ONLY；原 extraction 查询和 Worker、TapTouch 接入正常运行。workspace 内部可调用既有服务逻辑而不经旧 HTTP。false 时原界面/路由行为保持不变。

回滚切 false、停止 workspace Worker，保留新表与原件；不把新正式记录自动转旧 Case，不 downgrade 有数据迁移。历史新结果仍可经只读 workspace GET 查看。部署/切换必须在任务验收之外由负责人执行。


## 7. 进程和迁移补充约束

单店scope锁实现放在postgres_workspace_repository.py内的静态函数`lock_workspace_scope(session, tenant_id, store_id)`，旧上游Repository仅导入此函数，不实例化工作台Service；使用PostgreSQL hashtextextended参数绑定，不自行拼SQL。新上游版本的锁键由输入tenant/store产生，与是否启用工作台无关。

sync_sources对用户作废的upload文档不再恢复为ready，对completed发票不重建自动关系；上游voided最新版本不得回退到旧active。上传编辑的draft source已存在后不允许retry重新抽取；需要新文件时创建新document，旧document按正常作废/重开流程处理。

单例Scope行在首次intake/sync事务按锁后创建；GET不得创建Scope。generation初值0，首次写入触发+1。revision初值1，首次写入current_revision或用户动作按规定递增一次，幂等重放不递增。纯runtime心跳与last_sync_at更新不递增generation，否则每3秒所有预览都失效。

锁外匹配无可选组合时 result=null；save_preview只更新match_status/candidates派生依据并清preview_stale，不创建假PreviewResult。候选列表在GET使用同一纯函数根据当前scope快照计算，GET不持久化；正式confirm仍校验generation防陈旧选择。

`/history`固定复用CaseQueuePage(readOnly=true)，展示旧差异历史；旧清洁核对的既有ID/CSV读取继续保留，不在本版本新增全量历史搜索模块。回滚false仍保留新confirmation只读API，但导航回到旧系统；不许自动删除新数据。


## 8. Hash与代次规则

canonical JSON固定UTF-8、ensure_ascii=False、对象键字典序、无空白分隔符，金额沿用Schema序列化的十进制字符串，不转float。input_sha256包含按document_id排序的完整payload及revision_id、selection_origin、规则版本、容差、scope_generation；不可仅hash UI显示文本。

影响候选资格的intake-ready、编辑、source更新/void、confirm占用、reopen释放、用户void都推进scope.generation并标记其他未完成invoice preview_stale；investigate仅加备注、心跳、幂等重放不推进scope代次。confirm先校验旧generation，再保存当前正式结果，随后推进generation使其他发票重算；本次完成发票不失效。save_preview纯保存同一输入计算，不推进scope代次，避免循环重算。
