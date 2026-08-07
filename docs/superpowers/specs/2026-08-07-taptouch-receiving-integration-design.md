# Taptouch Receiving Integration 与发票对账产品设计

日期：2026-08-07
状态：已通过对话确认，等待书面规格复核

## 1. 决策摘要

IVIDA Invoice Reconciliation 应定位为 **Taptouch Back Office 的可集成发票与收货对账模块**，而不是 IVIDA 自身的应付账款系统，也不是对 Zeemart 的完整复制。

模块利用 Taptouch 已有或未来可提供的门店、供应商、SKU、库存和结构化收货数据，对外部供应商 Invoice 进行 AI 数字化，并判断发票内容是否被实际收货事实支持。

本次开发采用 Taptouch-ready MVP：

- Supplier Invoice 继续通过文件上传、MinerU、LLM 和人工审核进入对账；
- Taptouch Receiving Record 通过结构化接口导入，不经过 OCR 或 LLM；
- 外部 Receive Note PDF/图片上传继续作为兼容路径；
- 所有来源最终形成统一、不可变、可审计的可信业务版本；
- 当前确定性对账和企业 Case 流程保持可用；
- 数量核销、重复发票、多租户隔离和简单工作流按后续阶段独立实施。

## 2. 产品依据与推断边界

### 2.1 可验证依据

IVIDA Smart Technologies 的公开产品面向餐厅、咖啡店和零售商，提供 POS、云端管理与定制 Back Office：

- https://www.ivida.com.au/
- https://www.ivida.com.au/about/

Taptouch 公开产品能力包括 Supplier & Stock Management、Receiving、Reordering、Multi-store 和采购/收货成本控制：

- https://taptouchpos.com/retail/product-inventory/

Zeemart 公开流程可用于参考发票上传、订单关联和三单匹配交互，但不能作为 IVIDA 已确认需求：

- https://support.zeemart.co/en/articles/9418159-how-to-upload-invoices
- https://support.zeemart.co/en/articles/10598144-how-to-digitise-invoices

### 2.2 明确推断

公开资料没有给出 Taptouch 内部 Receiving API、Webhook、身份协议或正式 Invoice Reconciliation 需求。因此本设计只建立可替换的集成边界和本地模拟适配器，不声称已完成真实 Taptouch 集成。

项目中的评估单据是 synthetic dataset，只能作为工程测试资产，不能证明 IVIDA 的生产业务规则。

### 2.3 不进入项目文档的内容

个人职业资料只用于理解产品方向，不写入项目业务规格。设计以产品公开能力和项目需求为依据，不以个人经历作为系统要求。

## 3. 目标与非目标

### 3.1 本次目标

1. 修正“所有 Receive Note 都必须经过 OCR”的业务偏差。
2. 建立结构化 Taptouch Receiving 导入能力。
3. 记录文档来源、上游身份、信任方式和版本。
4. 保证重复推送幂等、上游修订不可覆盖历史版本。
5. 让候选和对账页面明确展示收货数据来源。
6. 保持现有 Invoice 上传、AI 抽取、审核、对账和异常 Case 回归兼容。
7. 用文档清楚区分当前实现、已确认阶段和未来演进。

### 3.2 本次非目标

- 建设完整 Purchase Order 系统；
- 建设采购商城、供应商下单或采购审批；
- 替代 Taptouch 的商品、库存、门店和供应商主数据；
- 接入未经提供的真实 Taptouch API；
- 银行付款、会计总账或税务申报；
- 完整多租户重构；
- Receiving Line 数量核销；
- 简单/企业工作流切换；
- Credit Note 和正式财务冲销；
- 通用可配置审批引擎。

PO 号在本阶段继续作为 Invoice 与 Receiving Record 上的可选关联信号，不成为独立业务对象。

## 4. 参与者与职责

| 参与者 | 职责 |
|---|---|
| 门店员工 | 在 Taptouch 记录实际收货，或上传外部收货文件 |
| 财务/运营审核人员 | 上传和确认 Supplier Invoice，选择收货候选，处理异常 |
| 管理员 | 管理企业模式下的异常审批，并使用内部模型质量工具 |
| Taptouch | 提供品牌、门店、供应商、SKU 和结构化 Receiving 上下文 |
| Invoice Reconciliation 模块 | 数字化发票、导入收货、匹配候选、确定性对账和保存审计 |
| MinerU 与 LLM | 只处理需要理解的外部文件，不处理可信结构化 Receiving |

## 5. 主业务流程

### 5.1 Taptouch 结构化收货主路径

1. 门店在 Taptouch 完成收货。
2. Taptouch 形成结构化 Receiving Record。
3. 集成接口接收 Receiving payload。
4. 系统验证集成身份、上下文和 Schema。
5. 系统映射为统一 `ReceiveNote` 业务模型。
6. 系统保存 `upstream_authoritative` 不可变版本和导入审计。
7. 该版本进入 Invoice 候选范围。

该路径不创建 MinerU Run、LLM Draft、Token、模型 Evidence 或虚假人工批准记录。

### 5.2 外部 Receive Note 兼容路径

1. 用户上传 PDF 或图片。
2. MinerU 解析版面与表格。
3. LLM 映射为 `ReceiveNote` Schema。
4. 系统执行校验并生成 Draft。
5. 人工核对原文、修改并批准。
6. `human_approved` 版本进入候选范围。

### 5.3 Supplier Invoice 路径

1. 用户上传发票文件。
2. MinerU 和 LLM 完成解析、规范化和 Evidence 映射。
3. 人工检查类型、字段、证据和 Validation Issues。
4. 人工批准不可变 Invoice Version。
5. 系统在允许的业务范围内生成 Receiving 候选。
6. 用户选择一个或多个候选并运行确定性对账。

### 5.4 结果分流

- 无实质差异：保存 Reconciliation 快照，不创建额外 Case；
- 存在 mismatch、invoice-only、receive-note-only、PO 冲突或币种冲突：保存快照并创建 Exception Case；
- Case 不修改历史 Reconciliation，只记录差异处置过程。

## 6. 统一来源与信任模型

### 6.1 来源类型

| `source_kind` | 含义 | 处理方式 |
|---|---|---|
| `invoice_upload` | 外部 Supplier Invoice 文件 | MinerU + LLM + 人工审核 |
| `external_receive_note_upload` | 外部 Receive Note 文件 | MinerU + LLM + 人工审核 |
| `taptouch_receiving` | Taptouch 结构化收货 | Schema 映射 + 上游权威校验 |

### 6.2 信任方式

| `trust_method` | 含义 | 是否可对账 |
|---|---|---|
| `human_approved` | 上传文件经过人工确认 | 是 |
| `upstream_authoritative` | 来自已认证的 Taptouch 上游 | 是 |
| `untrusted` | 校验失败或来源未确认 | 否 |

对账应用服务依赖“可信业务版本”接口，而不是依赖文档必须来自某个具体抽取流程。

### 6.3 可信版本共同属性

- 内部 Version ID；
- Document Type；
- 不可变规范化 JSON；
- Source Kind；
- Trust Method；
- 外部客户、品牌、门店和供应商 ID；
- 外部记录 ID 和外部版本；
- 上游更新时间；
- 内部创建时间；
- 作废/失效状态；
- 审计来源。

现有 `document_versions` 升级为统一 canonical version 表，而不是再建立一套无法被现有 Reconciliation 外键直接引用的平行版本表。迁移要求：

- `task_id`、`source_draft_id`、`version_number` 和 `created_by` 对结构化导入允许为空；
- 新增 `source_kind`、`trust_method`、`source_system` 和外部上下文字段；
- 现有数据回填为上传来源和 `human_approved`；
- 上传来源继续要求 Task、Draft 和人工创建者；
- `taptouch_receiving` 禁止关联虚假的 Task、Draft 或人工创建者；
- Taptouch 有效导入使用 `status=approved`、`trust_method=upstream_authoritative`、`approved_by=null`，并以导入时间记录 `approved_at`；
- 数据库 Check Constraint 验证上述来源组合，不能只依赖应用代码。

## 7. Taptouch Receiving 导入契约

### 7.1 接口

```text
POST /api/integrations/taptouch/receiving-records
Authorization: Bearer <integration-token>
```

浏览器 Reviewer Session 不能替代集成身份。MVP Token 从环境变量读取，不写入 Git、日志或数据库。

### 7.2 必需业务字段

- `external_tenant_id`
- `external_brand_id`
- `external_store_id`
- `external_supplier_id`
- `external_receiving_id`
- `external_version`，MVP 定义为从 1 开始单调递增的整数
- `record_status`，只允许 `active` 或 `voided`
- `document_number`
- `received_at` 或业务收货日期
- `currency`
- 至少一条商品行
- 商品行的 SKU 或描述
- 正数实收数量
- `upstream_updated_at`

单价、行金额、税额和 PO 号为可选字段。未知价格必须使用 `null`，不能伪造为零。

### 7.3 响应语义

| 场景 | 状态码 | 结果 |
|---|---:|---|
| 首次导入 | 201 | 创建可信版本 |
| 同一外部版本重复推送 | 200 | 返回已有版本 |
| 新外部版本 | 201 | 创建新的不可变版本 |
| Token 缺失或错误 | 401 | 拒绝请求 |
| Payload/Schema 错误 | 422 | 返回字段路径和原因 |
| 外部版本倒退 | 409 | 拒绝覆盖较新版本 |
| 外部身份发生冲突 | 409 | 拒绝并要求调查 |
| 临时基础设施故障 | 503 | 允许上游重试 |

### 7.4 幂等键

```text
source_system
+ external_tenant_id
+ external_store_id
+ external_receiving_id
+ external_version
```

幂等检查与版本写入必须处于数据库事务中，避免并发重复创建。

### 7.5 上游修改与作废

- 相同外部版本不得产生新记录；
- 更高外部版本创建新的内部不可变版本；
- 较低外部版本返回冲突；
- 上游作废产生明确的失效版本或状态，不物理删除历史；
- 已参与历史 Reconciliation 的版本始终可读取；
- 新候选只展示当前有效的最新版本。

## 8. 结构边界与现有模型兼容

现有 `ExtractionTask`、`ExtractionRun`、`DocumentDraft` 和 `DocumentVersion` 对文件抽取仍然有效，但结构化导入不应伪造模型运行。

实现应引入一个统一的可信文档读取边界，例如领域端口表达的 `TrustedDocumentVersion`，供以下消费者使用：

- approved-version 列表；
- Candidate Matching；
- Reconciliation Application Service；
- 历史导出；
- Case Detail。

文件路径通过人工批准版本实现该端口；Taptouch Receiving 路径通过上游权威版本实现该端口。消费者不根据来源重复实现业务规则。

具体数据库实现固定为扩展现有 `document_versions`：

- 文件路径仍由 `task_id + source_draft_id` 建立来源链；
- Taptouch 路径由 `source_system + external_tenant_id + external_store_id + external_receiving_id + external_version` 建立来源链；
- 为 Taptouch 来源增加上述五列的唯一约束；
- `version_number` 对上传路径继续表示 Task 内人工版本号，对集成路径必须为空；
- `external_version` 对集成路径表示上游单调版本号，两者不能混用；
- Reconciliation 和 `reconciliation_receive_notes` 继续引用同一个 `document_versions.version_id`，无需多态外键；
- Review Queue 只枚举拥有 Task/Draft 的文件版本；
- Approved Version 和对账查询同时读取 `human_approved` 与 `upstream_authoritative` 版本。

不得通过创建虚假文件名、虚假 Extraction Run、系统冒充 Reviewer 或虚假 Review Action 来复用旧流程。

## 9. 疑似重复 Receive Note

结构化 Receiving 和上传 Receive Note 可能表示同一业务事实。

系统根据以下信息产生疑似重复提示：

- 同一外部客户、品牌和门店；
- 同一供应商；
- 相同收货单号；
- 相同或接近的日期；
- 高度重叠的商品和数量。

处理原则：

- 不自动删除；
- 不自动合并；
- 候选排序优先 Taptouch 结构化来源；
- 明确显示疑似重复原因；
- 用户选择实际参与对账的版本；
- 被排除记录仍保留审计历史。

阶段一只实现来源优先级和可识别的重复信号；完整跨来源去重可以与阶段二的重复发票控制一起增强。

## 10. 页面设计

### 10.1 Upload

- 保留 Supplier Invoice 和 External Receive Note 上传；
- 明确说明 Taptouch Receiving 由系统同步，不需要上传；
- 不向普通用户展示 Integration Token 或同步调试入口。

### 10.2 Review

- AI 抽取文件继续进入人工审核队列；
- 有效的 Taptouch Receiving 不进入人工审核队列；
- 导入失败进入 Integration Error/日志，不创建模型 Draft；
- 普通审核页面不显示 MinerU、Prompt、Token 等非必要工程信息作为主操作内容。

### 10.3 Reconcile

候选必须显示：

- `Taptouch Receiving` 或 `External Receive Note` 来源徽标；
- 门店、供应商和收货日期；
- 外部记录 ID；
- 上游更新时间；
- 是否为当前有效版本；
- 候选信号和解释性分数。

Taptouch 来源可以优先排序，但用户仍负责确认选择。

### 10.4 Cases

阶段一只增加来源和上游上下文展示，不改变现有企业 Case 状态机。

## 11. 简单模式与企业模式目标设计

### 11.1 简单模式

适合单店和小商户：异常 Case 自动分配给当前操作人，处理完全部差异后直接完成或作废，不强制认领、改派和第二人审批。

### 11.2 企业模式

适合多门店集团：保留 `unassigned → in_progress → pending_approval/pending_void → approved/voided`，Reviewer 处理，Admin/Manager 审批。

### 11.3 阶段边界

阶段一不实现模式切换。未来先使用服务端策略决定模式，并把模式快照写入 Case；接入 Taptouch 租户配置后再升级为客户/品牌级策略。前端不能自行指定模式绕过审批。

## 12. 数量核销目标设计

当前 Reconciliation 相互独立，可能重复使用同一收货数量。阶段二必须引入 Receiving Line Allocation：

- `reserved`：异常 Case 调查期间预留；
- `committed`：对账完成后正式核销；
- `released`：对账作废后释放。

一个 Receiving Line 可以支持多张分批 Invoice，但 `reserved + committed` 不得超过实收数量。创建 Reconciliation 和 Allocation 必须在同一数据库事务中重新检查剩余数量并锁定相关行。

阶段一不得在文档或界面中声称已经解决重复核销。

## 13. 异常修正目标设计

现有 Case Resolution 保留，但后续增强明确下一步动作：

- `business_exception`：允许完成或提交批准；
- `document_data_error`：作废当前尝试并返回文档修订；
- `matching_error`：作废当前尝试并返回候选重选；
- `waiting_for_documents`：保持等待，阻止完成。

`voided` 只表示当前 Reconciliation Attempt 无效，不等于删除原始发票、在会计系统冲销或要求供应商开具 Credit Note。

## 14. 安全、日志与隐私

- 集成接口使用独立服务凭证；
- Token 只从运行环境读取；
- 日志不得记录 Token、完整认证头或不必要的完整 Payload；
- 数据访问必须为未来租户隔离保留外部客户/品牌/门店键；
- 候选匹配不能把跨客户数据作为低分候选；
- API 错误返回稳定代码和字段路径，不返回数据库连接信息；
- 上游数据、版本和作废动作写入追加式审计。

## 15. 开发阶段

### 阶段一：Taptouch-ready Receiving MVP

本次实施：

- 产品定位和业务文档；
- Source Kind 与 Trust Method；
- 结构化 Receiving 领域端口；
- 本地模拟适配器；
- 受保护的导入 API；
- 外部身份、幂等、版本和失效语义；
- 统一可信版本读取；
- Reconcile 来源展示；
- 数据库、API、服务和前端测试；
- 现有流程回归。

### 阶段二：业务正确性

- 客户、品牌、门店和供应商候选隔离；
- Duplicate Invoice 控制；
- Receiving Line Allocation；
- 并发事务锁；
- 超额开票与剩余数量；
- Reconciliation supersede。

### 阶段三：工作流精简

- Simple/Enterprise 模式；
- Case 模式快照；
- 简单模式直达完成；
- 文档错误修订闭环；
- 匹配错误重选闭环；
- 等待材料状态和提醒；
- 面向小商户的简化界面。

## 16. 文档变更清单

阶段一新增：

- `docs/business/00-product-positioning.md`
- `docs/business/02-taptouch-receiving-integration.md`
- `docs/business/08-product-gaps-and-roadmap.md`

阶段一修改：

- `README.md`
- `docs/README.md`
- `docs/business/01-business-overview.md`
- `docs/business/03-document-lifecycle.md`
- `docs/business/05-review-and-versioning.md`
- `docs/business/06-reconciliation-rules.md`
- `docs/reference/11-api-contracts.md`
- `docs/reference/12-database-dictionary.md`
- 相关代码—文档映射文件。

所有文档必须明确标记 `已实现`、`本阶段` 与 `未来演进`，不得把设计目标写成当前能力。

## 17. 测试策略

### 17.1 领域与服务测试

- Taptouch payload 映射为合法 `ReceiveNote`；
- 未知价格保持 `null`；
- 结构化导入不调用 MinerU 或 LLM；
- 无效业务上下文和商品行被拒绝；
- Trust Method 决定是否可进入对账。

### 17.2 幂等与数据库测试

- 同一外部版本重复导入返回已有记录；
- 并发重复请求只创建一个版本；
- 更高外部版本创建新版本；
- 较低版本返回冲突；
- 上游作废后不再进入新候选；
- 历史 Reconciliation 仍能读取旧版本。

### 17.3 API 测试

- 缺失/错误 Integration Token 返回 401；
- 首次创建 201，幂等重放 200；
- Schema 错误 422；
- 身份和版本冲突 409；
- 临时基础设施错误映射为稳定服务错误。

### 17.4 前端测试

- Upload 页面说明结构化同步路径；
- 候选正确显示来源、门店和外部 ID；
- Taptouch 来源优先但不自动选中；
- 外部 Receive Note 兼容流程不退化。

### 17.5 回归测试

- Invoice 上传与抽取；
- Review Version 创建、编辑和批准；
- Candidate Matching；
- 一对多 Reconciliation；
- Case 创建、认领、提交和审批；
- CSV 历史导出；
- Quality Lab 与反馈治理。

## 18. 阶段一验收标准

1. 可以用模拟 Taptouch payload 导入结构化 Receiving。
2. 导入过程中没有 MinerU、LLM、Token 计量或模型 Evidence。
3. 相同外部版本重复推送不会产生重复记录。
4. 上游新版本创建新不可变版本并保留旧版本。
5. 可以上传并批准 Supplier Invoice。
6. Reconcile 页面显示 Taptouch Receiving 候选及来源。
7. 可以选择一条或多条 Receiving 执行现有确定性对账。
8. 正常结果保存，异常结果创建 Case。
9. 外部 Receive Note 上传和人工批准路径继续工作。
10. 自动化测试和文档同步检查通过。

## 19. 已确认的关键决策

- IVIDA/Taptouch 是产品提供方，餐厅和零售商是模块用户；
- 采用 Taptouch Back Office 模块定位；
- Zeemart 只作参考，不定义 IVIDA 业务；
- 不擅自增加完整 PO 系统；
- 结构化 Receiving 是主路径，文件 Receive Note 是兼容路径；
- 阶段一先建立正确集成边界，不一次实现全部生产能力；
- Superpowers 只参与设计和计划，不参与代码开发。
