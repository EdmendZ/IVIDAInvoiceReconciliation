# 03 固定接口契约

## 1. 通用 HTTP 规则

路径前缀 `/api/workspace`，JSON snake_case，金额字符串，成功以裸 DTO 返回。所有接口复用 HttpOnly session；业务接口要求 reviewer 或 admin；对象不属于配置 scope 返回 404。`GET /runtime` 同样需登录，enabled=false 时返回 enabled:false、worker_online:false、两个时间字段null，不要求配置scope；其余 workspace 写接口在disabled时返回409 INVALID_TRANSITION，只读查询需要已配置scope。401/403通过workspace路由异常映射返回本章统一错误结构，不能直接泄漏旧字符串detail。

所有 POST/PATCH/PUT 必须有 `Idempotency-Key: <UUID>`。同 key＋同 actor＋同请求 hash 返回原成功响应；同 key 不同请求返回 409 IDEMPOTENCY_CONFLICT。请求 hash 为 method＋path＋canonical body SHA-256，文件上传 body 用 type＋文件 SHA-256＋原始文件名替代，不能把 multipart boundary 纳入 hash。成功响应持久化与业务 mutation 同事务。POST 原件先检索 key 再存对象；并发同 key 由 scope 锁后二次检查，重复对象仅清理本次副本。GET 无幂等 key。

所有修改已有文档请求携带 `expected_revision`，作用于 workspace document，而非旧 Version。409 返回最新 revision，客户端刷新，禁止自动重放用户决定。PATCH 只接受完整表单 payload，不接受任意 JSON Patch 路径。

统一错误：

```json
{"detail":{"code":"REVISION_CONFLICT","message":"单据已更新，请查看最新内容","document_id":"uuid","current_revision":7}}
```

message 中文、不得包含凭据/SQL/对象存储路径。可选键 document_id/current_revision 不适用时省略。400：INVALID_REQUEST；401：AUTH_REQUIRED；403：FORBIDDEN；404：DOCUMENT_NOT_FOUND；409：REVISION_CONFLICT / PREVIEW_STALE / SOURCE_REVIEW_REQUIRED / SOURCE_VOIDED / RECEIVING_IN_USE / IDEMPOTENCY_CONFLICT / INVALID_TRANSITION / LEGACY_READ_ONLY；422：VALIDATION_BLOCKED / UNRESOLVED_MATCH / UNVERIFIED_NOT_ACKNOWLEDGED / RESOLUTION_NOTE_REQUIRED / SUBJECT_CONFLICT / PARTIAL_ALLOCATION_UNSUPPORTED / DUPLICATE_INVOICE / INVALID_FILE；503：STORAGE_UNAVAILABLE / WORKSPACE_UNAVAILABLE。意外异常统一 500 INTERNAL_ERROR＋服务端 request_id 日志。

## 2. 数据 DTO

字段未写 nullable 即必填。List 总是数组，空用 []；不可用的数值用 null，禁止 0 冒充未知。

`DocumentSummary`：document_id、document_type、source_kind、revision、processing_status、display_status、document_number nullable str、supplier_name nullable str、document_date nullable date、selected_document_ids UUID[]、source_changed bool、updated_at UTC、error_code nullable str。列表不能返回原件 bytes、全部证据、全部结果。

`DocumentDetail`：

```text
document: DocumentSummary
review_status: open|investigating|completed|null
match_status: waiting_counterpart|needs_selection|selected
selection_origin: automatic|manual|null
selection_note: string|null
current_revision: RevisionView|null
candidates: Candidate[]
selected_receivings: RevisionView[]
selected_receiving_source_ids: UUID[] // 所选收货中 source_kind=upload，可通过既有 source 路由读取原件
related_invoices: DocumentSummary[]   // Receive Note 的反向当前关系；Invoice 固定 []
preview: PreviewView|null
preview_stale: bool
confirmation: ConfirmationView|null
actions: ActionView[]                 最新 50 条，旧记录通过 actions 分页接口读取
source_url_available: bool
```

`RevisionView`：revision_id、document_id、sequence、origin、payload（Invoice/ReceiveNote）、evidence（现有 FieldEvidence[]）、validation_issues（原 ValidationIssue[]）、evidence_origin_revision_id nullable、created_at。revision 不包含原件下载地址。

`Candidate`：document_id、revision_id、document_number、score integer 0..100、eligible bool、reason_codes string[]、source_kind、supplier_name nullable、document_date nullable、already_used bool。score 为规则分，无 confidence 概率字段。已占用收货保留在搜索结果供解释，但不能被选中。

`MetricComparison`：invoice_value decimal-string|null、received_value decimal-string|null、difference decimal-string|null、status=equal|within_tolerance|different|unverified、reason_code string|null。difference=invoice-received。

`LineResult`：match_key、sku nullable、description、invoice_unit nullable、received_unit nullable、quantity/price/amount（各 MetricComparison）、status=equal|within_tolerance|different|unverified|invoice_only|receive_only、reason_codes string[]、invoice_line_indexes int[]、receive_lines `{document_id,line_index}`[]。

`PreviewResult`：

```text
outcome: consistent|difference|blocked
coverage: quantity_only|quantity_and_price|quantity_and_amount|full
blocking_codes: string[]
unverified_dimensions: string[]  // 如 price, amount, document_total, tax
lines: LineResult[]
summary: {total_lines:int, different_lines:int, unverified_lines:int}
subject: {supplier:equal|unverified|conflict, currency:equal|conflict, scope:equal}
```

coverage 指商品行维度覆盖，不代表税费或总应付款完全验证。document_total/tax 本版本固定未跨单据核验，必须出现在 unverified_dimensions；页面写“商品明细一致”，禁止“付款金额核验通过”。

`PreviewView`：preview_id、input_revision_ids、scope_generation、rule_version、tolerances、input_sha256、result PreviewResult、created_at。

`ConfirmationView`：confirmation_id、preview_id、invoice_number str、receive_note_numbers str[]、resolution、note nullable、acknowledged_unverified_dimensions、result_snapshot PreviewResult、rule_version、tolerances、input_revision_ids、actor_id、created_at。

`ActionView`：action_id、action、actor_id nullable、reason nullable、old_revision nullable、new_revision、confirmation_id nullable、created_at。

## 3. HTTP 路由清单（完整）

| 方法/路径 | 请求 | 成功 |
|---|---|---|
| POST /documents | multipart file＋document_type；不要让前端传 tenant/store | 201 `{document:DocumentSummary,task_id,run_id,duplicate:bool}` |
| GET /documents | type=invoice/receive_note（默认 invoice）；status 可重复 display_status；q 可选≤100字符；page≥1默认1；page_size 1..100默认20 | 200 `{items:DocumentSummary[],page,page_size,total}` |
| GET /documents/{id} | 无 | 200 DocumentDetail |
| GET /documents/{id}/source | 无；仅 upload | 200 streaming 原件；upstream 返回404，无伪造文件 |
| GET /documents/{id}/actions | page/page_size 同列表 | 200 `{items:ActionView[],page,page_size,total}` |
| PATCH /documents/{id} | `{expected_revision,document:Invoice|ReceiveNote,reason:string}` | 200 DocumentSummary |
| PUT /documents/{id}/selection | `{expected_revision,receive_document_ids:UUID[],reason:string}`；需要幂等 key，与 POST/PATCH 一致 | 200 DocumentSummary |
| POST /documents/{id}/investigate | `{expected_revision,note:string}` | 200 DocumentSummary |
| POST /documents/{id}/confirm | 见下 | 201 `{document:DocumentSummary,confirmation:ConfirmationView}` |
| POST /documents/{id}/reopen | `{expected_revision,reason:string}` | 200 DocumentSummary |
| POST /documents/{id}/void | `{expected_revision,reason:string}` | 200 DocumentSummary |
| POST /documents/{id}/retry | `{expected_revision}` | 202 `{document:DocumentSummary,run_id}` |
| GET /confirmations/{id} | 无 | 200 ConfirmationView，历史也可读 |
| GET /confirmations/{id}/export.csv | 无 | 200 text/csv UTF-8 BOM；按存储 snapshot 导出 |
| GET /runtime | 无 | 200 `{enabled:bool,worker_online:bool,last_sync_at:UTC|null,preview_lag_seconds:int|null}` |

PUT selection：空列表清除人工选择并恢复自动模式；非空列表标 manual，1..100、无重复 ID；只允许未完成 invoice，候选必须 ready、scope/主体一致、未被其他正式结果占用。不得偷偷改发票字段。reason trim 后 1..2000。

confirm：

```json
{
  "expected_revision": 7,
  "preview_id": "uuid",
  "acknowledged_sources": true,
  "acknowledged_unverified_dimensions": ["tax", "document_total"],
  "resolution": "matched",
  "note": null
}
```

acknowledged_sources 必须 true；unverified 集合须与当前 preview 完全相同（排序无关、不得重复）。blocked 禁止确认；difference 仅 resolved_with_note，trim 后 note 1..2000；consistent 仅 matched，note 可空。所有其他 reason/note 约束也为 1..2000，HTTP 日志不输出正文或证据。

GET source 以服务端读取当前 scope 原件并流式转发，不暴露 MinIO 凭据；Content-Disposition inline、正确 MIME、nosniff、Cache-Control private,no-store。PNG/JPEG/PDF 复用已验证格式。CSV 列固定：confirmation_id,invoice_number,receive_note_numbers,rule_version,resolution,note,match_key,sku,description,invoice_quantity,received_quantity,quantity_difference,quantity_status,price_status,amount_status。所有单元格以 =,+,-,@,TAB,CR 开头时前置单引号防公式注入；负十进制数值列保留数值文本，只有确定来自 Decimal 的数值可豁免。导出数据英文值不翻译。

发票核对布局使用现有每个 document 的 source 路由，不新增批量文件接口。多张收货只加载当前标签原件；切换差异行时依据 `LineResult.receive_lines[].document_id` 切换相应标签。上游无上传原件时显示只读结构化来源，不伪造 PDF。

## 4. Python 模块接口

以下签名全部定义在指定文件，不允许另立实现入口。类型均来自 domain/workspace.py；UUID/datetime 使用现有项目风格。

```python
# workspace_matching.py（纯函数）
def normalize_identity(value: str) -> str: ...
def select_candidates(invoice: RevisionView, receivings: list[RevisionView],
                      used_ids: set[str]) -> MatchProposal: ...
# MatchProposal(status, candidates:list[Candidate], selected_document_ids:list[str])

# workspace_comparison.py（纯函数）
def compare_workspace(invoice: RevisionView, receivings: list[RevisionView]) -> PreviewResult: ...

# document_upload_service.py 增加；旧 upload 保持契约
def prepare_upload(self, *, document_type: DocumentType, filename: str,
                   data: bytes, purchase_order_hint: str | None = None) -> PreparedUpload: ...
# PreparedUpload(task:ExtractionTask)，完成验证/唯一对象写入，尚未写 SQL。
# 旧 upload 调 prepare_upload 再原 Repository.create；新工作台走原子 intake。

# workspace_service.py
class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository, upload_service: DocumentUploadService,
                 storage: ObjectStorage, scope: WorkspaceScopeKey): ...
    def upload(self, command: UploadCommand, actor: AuthenticatedUser, key: str) -> IntakeResponse: ...
    def list_documents(self, query: DocumentQuery) -> DocumentPage: ...
    def get_document(self, document_id: str) -> DocumentDetail: ...
    def get_actions(self, document_id: str, page: int, page_size: int) -> ActionPage: ...
    def edit(self, document_id: str, command: EditCommand, actor: AuthenticatedUser, key: str) -> DocumentSummary: ...
    def select(self, document_id: str, command: SelectionCommand, actor: AuthenticatedUser, key: str) -> DocumentSummary: ...
    def investigate(self, document_id: str, command: InvestigateCommand, actor: AuthenticatedUser, key: str) -> DocumentSummary: ...
    def confirm(self, document_id: str, command: ConfirmCommand, actor: AuthenticatedUser, key: str) -> ConfirmationResponse: ...
    def reopen(self, document_id: str, command: ReasonCommand, actor: AuthenticatedUser, key: str) -> DocumentSummary: ...
    def void(self, document_id: str, command: ReasonCommand, actor: AuthenticatedUser, key: str) -> DocumentSummary: ...
    def retry(self, document_id: str, command: RevisionCommand, actor: AuthenticatedUser, key: str) -> RetryResponse: ...
    def get_confirmation(self, confirmation_id: str) -> ConfirmationView: ...
    def source(self, document_id: str) -> SourceFile: ...
    def export(self, confirmation_id: str) -> str: ...
    def runtime(self) -> RuntimeView: ...
```

Command DTO 与 HTTP body 一一对应；UploadCommand(document_type,filename,data)，key 不在 body；WorkspaceScopeKey(tenant_id,store_id)；SourceFile(filename,content_type,data:bytes)；RuntimeView 同 HTTP；RevisionCommand(expected_revision)；ReasonCommand 再加 reason。IntakeResponse/ConfirmationResponse/RetryResponse/DocumentPage/ActionPage 与表中成功体完全相同。

```python
# workspace_ports.py；PostgresWorkspaceRepository 是唯一实现
class WorkspaceRepository(Protocol):
    def cached_request(self, scope, actor_id, key, request_hash) -> CachedResponse | None: ...
    def intake(self, scope, prepared: PreparedUpload, actor_id, key, request_hash) -> IntakeResponse: ...
    def list_documents(self, scope, query: DocumentQuery) -> DocumentPage: ...
    def get_document(self, scope, document_id) -> DocumentDetail: ...
    def get_actions(self, scope, document_id, page, page_size) -> ActionPage: ...
    def mutate(self, scope, document_id, operation: WorkspaceOperation, command: WorkspaceCommand,
               actor_id, key, request_hash) -> WorkspaceMutationResponse: ...
    def get_confirmation(self, scope, confirmation_id) -> ConfirmationView: ...
    def source_metadata(self, scope, document_id) -> SourceMetadata: ...
    def sync_sources(self, scope) -> SyncSummary: ...
    def pending_previews(self, scope, limit: int = 100) -> list[PreviewInput]: ...
    def save_preview(self, scope, input: PreviewInput, proposal: MatchProposal,
                     result: PreviewResult | None) -> bool: ...
    def runtime(self, scope) -> RuntimeView: ...

# workspace_worker.py
class WorkspaceWorker:
    def __init__(self, repository: WorkspaceRepository, scope: WorkspaceScopeKey): ...
    def tick(self) -> TickSummary: ...
    def run_forever(self, stop_event: threading.Event) -> None: ...
```

mutate operation 仅 edit/select/investigate/confirm/reopen/void/retry；通过内部显式分派实现，不接受任意函数或任意表更新。WorkspaceCommand 是上述命令的联合类型；WorkspaceMutationResponse 是 DocumentSummary/ConfirmationResponse/RetryResponse 的联合；具体 operation 与返回类型不一致为实现错误。

CachedResponse(status:int,body:dict)；SourceMetadata(filename,content_type,object_key)；SyncSummary(changed_documents:int,scope_generation:int)；PreviewInput(invoice:RevisionView,receivings:list[RevisionView],used_ids:set[str],scope_generation:int,document_revision:int,manual_selection_ids:list[str]|null)；TickSummary(synced:int,previews_saved:int,previews_discarded:int,errors:int)。pending_previews 不仅给已选组合，而是提供当店当前可选收货快照；save_preview 使用 generation＋document_revision CAS，冲突返回 false。

Repository 的确认事务内允许调用无副作用 matching/comparison 函数重验，不调用 Service，不访问外部网络。Service 负责命令/schema/权限语义校验，Repository 负责数据库当前状态、互斥、CAS、原子写入，不能只在 Service 检查一次。

## 5. 前端接口与组件边界

workspaceTypes.ts 逐项镜像本章 DTO（金额 string），不得 `any`；workspaceClient.ts 使用已有 api/upload/download 基础方法并提供：listDocuments/getDocument/getActions/uploadDocument/editDocument/selectReceivings/investigate/confirm/reopen/voidDocument/retry/getConfirmation/exportConfirmation/getRuntime。参数与 HTTP 一致。Idempotency-Key 在一次用户操作开始时生成、网络不确定重试复用，收到明确失败后新操作用新 key。

workspacePresentation.ts 仅含 `displayStatusLabel`、`metricStatusLabel`、`canConfirm(detail)`、`canEdit(detail)`、`canReopen(detail)`、`unverifiedSummary(result)`，不包含业务决策或网络调用。WorkspacePage(props:{onNavigate:(path:string)=>void})；DocumentPage(props:{documentId:string,onNavigate:(path:string)=>void})。DocumentPage 内的局部函数/组件可写在同文件，不能自行新建组件目录。

所有按钮允许性由后端重新判断；403/409 必须显示中文信息。409 刷新详情但保留尚未提交的本地输入并提示用户，不自动覆盖、不自动再提交。单页确认前显示关联收货、提取字段和未核验维度；源字段仍英文。原件显示 PDF iframe 或 img，来源字段/证据只当文本渲染，禁止 dangerouslySetInnerHTML。


## 6. 辅助契约的固定值

- `DocumentQuery(type="invoice",status:list[DisplayStatus]=[],q:str|None=None,page=1,page_size=20)`；q 对 document_number/supplier_name 做大小写不敏感字面子串查找，SQL escape `%`/`_`，不得把用户输入当模式。默认 updated_at DESC、document_id ASC 稳定分页。
- `PageQuery(page=1,page_size=20)`；`ActionPage` 按 created_at DESC、action_id DESC。
- `PreparedUpload(task:ExtractionTask)` 定义在 domain/workspace.py，仅这个现有 domain 类型可导入；不得把 SQL session 放进 DTO。
- `WorkspaceOperation` 固定 edit/select/investigate/confirm/reopen/void/retry。`DisplayStatus` 固定 processing/failed/cancelled/voided/waiting_counterpart/needs_attention/awaiting_confirmation/completed。
- `SyncSummary`/`TickSummary` errors 仅计数，异常详细写服务端日志；不得返回源文件内容。
- `DocumentDetail.confirmation` 为当前最新确认；reopen 后 current_confirmation_id置null，旧ID仍可GET，Action记录旧ID。
- `WorkspaceRevision.source_draft_id` 与 source_version_id 至多一个非空；首次 extracted/upstream 必须相应来源；manual 沿用前版 source_draft_id，同时 evidence_origin_revision_id 指向最初带证据的revision。
- `PreviewInput.manual_selection_ids=null` 表示自动模式，非空数组表示手动；selection API 空数组切自动，不能持久化manual空集合。
- `IntakeResponse` 的 duplicate 必填；首次false，同hash复用true；同幂等key重放返回原值不重新推算。被void的同hash原件不复用document，创建新document但仍保存原历史；不增加唯一hash数据库约束，去重由scope串行事务完成。
- 新 queued Run 的 provider/model_name沿用旧disabled provider的标识，status=queued、started_at/created_at/next_attempt_at=同一个now；其余字段使用现有ExtractionRun默认值，由原Worker填实际provider provenance。Task status=extracting，在intake同事务落库。
- 所有新增 Repository 方法的 scope参数均为WorkspaceScopeKey；actor_id/key/request_hash/document_id/confirmation_id为str；page/page_size为int；`WorkspaceCommand`为EditCommand/SelectionCommand/InvestigateCommand/ConfirmCommand/ReasonCommand/RevisionCommand，不能传dict绕过校验。
- Runtime.preview_lag_seconds是最早未完成且preview_stale发票的updated_at距now的非负整数秒，无失效记录为0，worker离线为null。
- 原件上传阶段最多沿用原`upload_max_bytes`；幂等日志hash不记录bytes；服务端白名单MIME由既有DocumentUploadService决定，不扩大文件类型。
- stable blocking_codes完整集合：EMPTY_ITEM_KEY/UNIT_UNVERIFIED/UNIT_CONFLICT/SUPPLIER_UNVERIFIED/SUPPLIER_CONFLICT/CURRENCY_CONFLICT/UNSUPPORTED_CURRENCY/SOURCE_VOIDED/VALIDATION_BLOCKED/DUPLICATE_INVOICE/RECEIVING_IN_USE；候选reason_codes只用于推荐，不能冒充阻断代码。


## 7. v1.0.2 导出契约补全

ConfirmationView 的 invoice_number 和 receive_note_numbers 由 Repository 根据该 confirmation 的不可变 invoice_revision_id/receive_revision_ids 读取 payload.document_number 生成，收货顺序与 input_revision_ids 一致。不得读取当前版本替代历史编号；无需新增数据库列、表或路由。Service.export 直接使用此 DTO 的历史编号与 result_snapshot 生成 CSV。T03 同时补齐领域 DTO 和往返测试，其他领域接口不变。
