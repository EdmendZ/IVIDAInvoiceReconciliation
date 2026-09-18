# 07 验收、迁移与发布门禁

## 1. 必须通过的业务场景

| ID | 固定输入/触发 | 必须结果 |
|---|---|---|
| A01 | 先上传 Invoice，后上传 RN | 首先等待；RN ready 后自动预览；用户不点开始匹配 |
| A02 | RN 先到，Invoice 后到 | RN 可独立录入；Invoice ready 后自动关联 |
| A03 | Invoice 10袋，同 PO RN 6＋4袋 | 自动预选两张；数量equal；未 confirm 不得 completed |
| A04 | 同供应商两张相同商品、无PO、同分 | needs_selection，禁止自动随便挑一张 |
| A05 | 不同供应商但数量金额一致 | 不自动关联；手动强选422 SUBJECT_CONFLICT |
| A06 | RN 缺价格金额、数量相同 | consistent/quantity_only；未核验维度必须展示并确认，禁止宣称全财务一致 |
| A07 | kg 与 carton、或单位缺失 | blocked，不聚合、不自动换算 |
| A08 | 纯中文描述不同 | 商品键不同，不坍缩为空；空键blocked |
| A09 | Invoice10袋、RN8袋 | difference，investigate 保存备注后仍未完成 |
| A10 | A09后新增同PO RN2袋 | 未完成自动组合更新，数量equal，仍需确认 |
| A11 | difference＋resolved_with_note | 非空备注才完成；原差异保留在snapshot和CSV |
| A12 | 编辑数量或更换所选收货 | revision递增、preview失效，旧preview confirm409 |
| A13 | 新上游版本/void与confirm并发 | 串行锁边界，不能确认已知旧版；完成后发生变化则source_changed不改snapshot |
| A14 | 两张发票并发确认同一RN | 只有一个成功，另一RECEIVING_IN_USE |
| A15 | confirm后网络丢响应，用同key重试 | 同confirmation_id，无重复快照/动作/占用 |
| A16 | 同key不同body | 409 IDEMPOTENCY_CONFLICT，无副作用 |
| A17 | 确认事务中注入Action写入失败 | confirmation/claims/document更新全部回滚 |
| A18 | Worker重启、重复tick、保存预览时generation变化 | 不丢等待任务、不产生重复修订；旧计算被丢弃 |
| A19 | 完成记录来源变化、reopen | 原confirmation不变，原因有审计，释放claims，再确认生成新ID |
| A20 | 对象范围外ID/未登录/普通用户访问Lab | 分别404/401/403；无数据泄露 |
| A21 | 上传同类型同hash | 同document/task/run，duplicate=true，不多次模型调用 |
| A22 | 同主体同Invoice编号不同文件 | 可以查看，确认阻断DUPLICATE_INVOICE，不自动删原件 |
| A23 | 部分税额未知 | 不因缺失税被当0误报税额冲突 |
| A24 | 两行同商品不同单价 | 不以加权价掩盖差异；price unverified/MULTIPLE_PRICES，amount独立核验 |
| A25 | 多次修改英文商品/证据/备注 | 语言保留英文原值，UI中文，接口enum保持英文 |
| A26 | enabled模式访问旧写接口 | 409 LEGACY_READ_ONLY；旧历史读取及导出可用 |
| A27 | 文件写成功SQL失败、重试 | 无孤立业务记录；只清理新建对象，不能删除先前共享原件 |
| A28 | pending/failed任务离开浏览器 | 后台继续；重新打开恢复状态，无手动开始提取 |
| A29 | 试图确认blocked预览/未ack未知维度 | 422且无confirmation，无自动改为成功 |
| A30 | 原件/CSV含HTML/公式 | 证据按文本渲染、下载授权，CSV不执行公式 |

## 2. 测试分层

- 纯规则：无需数据库/外部模型，Decimal 边界、匹配歧义、集合顺序、Unicode。
- Repository：真实 PostgreSQL；事务回滚、约束、锁、并发幂等、不可变触发器；测试会创建临时 schema，结束只删自己创建且名字匹配的 schema。
- API/worker：TestClient＋独立 Postgres＋Fake parser/normalizer/storage；完整先后到达场景，而非只 mock service 返回200。
- 前端：Vitest＋Testing Library；上传/自动等待/同页修订/一次确认/409不丢输入/终态只读；按钮不能绕过后端权限。
- 浏览器验收：桌面1440×900和窄屏390×844，上传入口、详情证据、长英文商品、多个RN、差异说明；不横向遮挡确认按钮。截图保存外部证据库，不能用 build 成功替代视觉验证。

## 3. 固定总门禁

```text
python tools/check_spec_contract.py --spec-root spec
python tools/check_task_scope.py --task Txx --base <task_base> --spec-root spec --evidence <external-freeze-record>
python -m pytest -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
python tools/check_documentation_sync.py --base-ref <release_base>
git diff --check <task_base>
```

真实 PostgreSQL 集成测试在本机可因无专用连接跳过，但 T03/T09/T11验收必须0跳过；外部服务不要求真实调用，不得编造模型准确率。Harness在外部保留命令exit_code、日志hash、测试结果和截图。基线已存在失败必须在派发前记录并由负责人处理，不允许任务偷偷带过。

T12 追加验收：开发管理员入口能创建、重复运行时重置同一用户并撤销旧 Session，production 环境拒绝执行；Python 启动入口必须代理现有 PowerShell 启动器，不复制进程管理逻辑；文档明确外部参考边界。

T13 追加验收：D04 production 环境在访问数据库或对象存储前拒绝；D05 一次运行得到六份英文 PDF 和双方分别等待、自动一致、数量差异四类可见结果；D06 同一范围重复执行不增加 Task、Run、Draft、Workspace Document、Revision 或 Preview；D07 只复用现有用例/Worker，输出不含 Secret，文档明确 demo fixture 不代表真实抽取或 TapTouch 接入。

T14 追加验收：D08 Party 可保留 `name=null` 与有依据的 business_number/address，并完成 JSON 往返；D09 提示词明确禁止把通用单据标题当供应商名称，缺失名称输出 null；D10 ValidationService 对通用标题产生 `SUPPLIER_NAME_GENERIC` warning；D11 匹配与重复检测在名称为空时仍安全优先使用双方 ABN，缺少双方可靠身份时保持 unverified。

T15 追加验收：D12 JSON 反序列化后的 DateTime 与原 ISO 字符串均能通过同一 UTC 进程起始时间校验；D13 只对已验证归属的记录停止其当前子孙进程和父进程，不按名称或端口误杀；D14 真实 start/stop/start 后四个本地组件均停止且可恢复，健康检查重新为 200。

T16 追加验收：D15 Invoice 先到或 Receive Note 先到均形成同一核对关系；从上传入口打开的收货在唯一关联后 replace 进入 Invoice，零关系不跳、多个关系不猜。D16 发票核对页同时显示 Invoice 与一张当前 Receive Note 原件，多张收货可切换，差异行可选择其来源收货；上游无原件明确说明。D17 文件重复继续打开既有 document，业务重复继续阻断确认；T16 不改变确认、claim、人工选择冻结和不可变快照规则。D18 1440px 双栏审查、1050px 以下纵向布局均可操作，结构化字段和一次确认入口保留。

T17 追加验收：D19 `/history` 默认列出当前 scope 全部 Confirmation，包括重开前旧快照，按创建时间与ID倒序稳定分页；摘要编号、供应商、收货编号和结果来自固定历史 revision/snapshot。D20 q 可字面搜索历史发票号、供应商、收货单号，outcome 可重复筛选且拒绝重复值；其他 scope 不泄露。D21 `/history/{id}` 只读展示完整快照、未核验维度、说明、操作人与时间并可导出原 CSV。D22 `/history/legacy` 保留旧 Case 只读查询，日常历史不出现认领、审批或修改入口，T17 不新增表、迁移或写操作。

T18 追加验收：D23 Windows PowerShell 5.1 的健康请求使用 `-UseBasicParsing`，HTTP 200 不再被 IE 解析异常误报为超时。D24 真实 start/stop/start 后 API、Extraction Worker、Workspace Worker、Frontend 均由状态记录安全管理，8200/5274 恢复响应，OpenAPI 包含当前 `/api/workspace/confirmations` 路由。

T19 追加验收：D25 核对页的每个未核验维度均显示原因、影响和处理方式，黄色提示明确其不是差异，并继续使用既有一次知情确认。D26 阻断项使用红色说明且确认保持禁用；真实差异独立提示必须填写处理说明，三类含义不混淆。D27 正式历史从固定 result_snapshot 使用同一未核验解释，仍无修改、审批或认领入口。D28 T19 不改变 API、数据库、匹配、确认请求体或历史快照。

T20 追加验收：D29 使用独立 `_workspace_test` PostgreSQL 数据库时，工作台 Repository 与端到端验收测试全部通过且无 skip。D30 迁移后的八张 `ws_` 表、JSONB 字段、幂等约束、确认快照、重开历史和并发收货占用均由真实 PostgreSQL 验证。D31 开发文档使用 `WORKSPACE_TEST_DATABASE_URL`，不把工作台测试指向演示库或生产库；T20 不改业务代码和数据契约。

T21 追加验收：D32 Invoice 核对详情根据现有修订和预览显示“按 ABN 匹配”“按名称匹配”“供应商未核验”或“供应商冲突”；供应商原始英文值仍按原样显示，名称比较仅使用既有规范化规则；多张收货依据不一致时逐项列出。D33 T21 不新增 API、字段、数据库表、外部身份映射、匹配规则或确认步骤，现有确认与历史页面行为保持不变。

## 4. 迁移与兼容验证

1. 使用生产相同 PostgreSQL 主版本的独立测试库，从20260807_14迁移至15；保留旧表和记录。
2. 对旧snapshot、approved version做前后hash比较，必须完全不变。
3. 新工作台不自动复制旧上传任务/Case；旧历史仍只读可查。要导入旧未完成业务须另外Spec，本版不悄悄转换状态。
4. 配置范围的现有上游active收货首次同步可进入工作台，但已被旧历史正式核对引用的上游收货必须标 legacy_used=true，不自动可选。此标记由同步读取旧 reconciliation 关系派生，不增加第九张表；若需要重用须留在旧流程处理，不允许工作台 override。
5. 初次启用前负责人确认历史占用清单；不把旧case.approved解释为实际付款。
6. compose启动API、原extraction-worker、新workspace-worker、frontend及原有基础设施；MinIO/database隔离沿用现有命名。
7. true/false开关回滚均验证；不能把false时的新快照丢弃或改成旧格式。不得在包含用户数据的库直接执行 downgrade。

## 5. Spec 自审与停止条件

已固定产品范围、页面、状态、规则、表、事务、HTTP、端口、文件、任务、验收与权限策略。任务开始不得有“实现者自行决定”的公共契约。

单店串行写、轮询最多100发票、整张收货独占、未知价格可数量确认、无税费跨单核验、无历史业务自动转换均是有意的 v1 限制，不得在执行中自行扩展。真实业务需要拆分收货/贷项单/自动批准/多店时必须新版本Spec。

冻结前由负责人确认这些限制及接口命名；冻结后如发现规范自身矛盾，状态是 blocked，而不是实现者自由补全。
