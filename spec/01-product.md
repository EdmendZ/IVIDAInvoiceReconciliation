# 01 产品与状态机

## 1. 目标与边界

单店操作员把 Invoice 和 Receive Note 先后录入。结构化收货可来自既有 TapTouch 原型接口；尚未证明真实 TapTouch 已接入。上传文件复用 MinerU＋文本模型提取。系统自动寻找关联、生成预览；人同页校正数据、确认关联、处理差异，最终一次确认。

无需额外点击开始提取、开始比对、认领、分派、交管理员审批。底层仍保存操作者、原件、机器输出、每次修订与正式结果。自动预览不具有已确认结果的业务含义。

范围固定为单商户单门店部署，配置 `WORKSPACE_TENANT_ID`、`WORKSPACE_STORE_ID`，WORKSPACE_ENABLED=true 时启动校验必须非空。浏览器用户 reviewer/admin 均能操作这个门店；不新增角色。机器收货接口既有身份授权继续有效。配置范围外的收货不得出现在工作台或参与计算。此版本不声称多租户产品隔离完备。

## 2. 页面

- `/`：工作台。上传按钮（类型 invoice/receive_note 必选）、筛选、分页列表。默认发票；可切到“未关联收货记录”。
- `/documents/{document_id}`：单据详情。发票显示原件/提取表单、候选及当前收货组合、核对预览、备注和确认入口；收货单显示原件/字段及关联发票，没有“确认对账”按钮。
- `/history`：旧对账/Case 页面只读入口。旧 URL 仍可读取；编辑按钮隐藏，服务端旧业务写接口拒绝，不能靠隐藏按钮控制。
- `/lab`：继续 admin 专用，不放在日常导航主项中；右上“管理工具”进入。
- 登录和会话沿用；主导航只有“工作台”“历史记录”，管理工具仅管理员可见。
- 中文标签；供应商、商品、原文、用户备注不翻译。AUD/GST 口径不改为人民币/中国增值税。
- 轮询：详情有处理/失效预览时每 3 秒；列表每 5 秒；浏览器隐藏时暂停，恢复时立即刷新。不得用轮询 GET 写入业务状态。

## 3. 三个独立状态维度

`Document.processing_status = processing | ready | failed | cancelled | voided`。

`Match.status = waiting_counterpart | needs_selection | selected`。selected 只是预览已选组合，另存 `selection_origin=automatic|manual`，不是最终确认。

`Review.status = open | investigating | completed`。仅 Invoice 使用。

首页 `display_status` 按以下顺序派生，禁止另存第四套状态：

1. voided → `voided`（已作废）；failed/cancelled → 对应异常状态；processing → `processing`。
2. completed → `completed`，即使有 `source_changed=true` 也保持完成并展示来源变更提醒。
3. open/investigating 且 `preview_stale=true` → `processing`（重新核对中）。
4. investigating → `needs_attention`（待核实）。
5. waiting_counterpart → `waiting_counterpart`（等待另一方单据）。
6. needs_selection → `needs_attention`；selected 且有 blocking/difference → `needs_attention`。
7. 其余 → `awaiting_confirmation`，显示“待确认”，不能显示“已完成”。

上述派生顺序仅针对 Invoice。Receive Note 的 processing/failed/cancelled/voided 优先，其余 ready 且被 ws_claims 或旧历史占用则显示 completed（已关联），未占用则 waiting_counterpart（等待发票确认）；不显示“需要单独批准收货单”。

未知价格是 coverage 信息，不自动成为真实业务差异；未知必需数量/单位、未解决主体、来源失效则阻止确认。差异未解决不自动逾期报警。本版本不实现 SLA。

## 4. 允许的用户动作

- 上传后自动进入 processing，不需要第二个提取请求。
- ready 的未确认上传单据可编辑；每次显式保存创建修订，触发重算；不能逐按键创建修订。上游权威收货只读，不允许在本系统改其事实。
- 用户可手动选择多张候选收货并填写原因；不可跨供应商/币种/门店强行关联。
- `investigate`：保存非空备注，进入 investigating；不生成正式对账，不占用收货。
- `confirm`：一次确认所有所选上传单据字段、关联和当前预览；无真实差异时 `resolution=matched`，有差异时 `resolution=resolved_with_note` 且必须非空说明。界面明确“按说明关闭，原差异仍保留”，不能称差异消失。
- 等待补货/联系供应商的操作用 investigate；不能通过这些选项标记完成。
- 来源更新导致已完成记录变化：显示提醒，历史快照不修改。需要纠正时 `reopen`：要求原因，旧结果保留、收货占用释放、重新预览，下次确认生成新结果。
- 对未完成上传单据可 `void`，必须备注；已完成发票必须先 reopen 才可作废。被正式结果占用的收货不得直接作废；先处理关联发票。上游 void 只能由上游导入产生。
- 失败/取消任务可 retry；同一时刻只允许一个活跃 Run；重试不改变 document_id。

## 5. 一次确认的具体含义

按钮：“确认核对结果”。提交 `expected_revision` 和 `preview_id`，强制勾选“我已核对发票、所选收货记录与未核验项目”。服务端重验输入后保存不可变正式快照。同店操作员无需重复批准每张上传单据，也无需充当另一个管理员。

自动预选候选最多是降低点击成本，必须在确认页清晰列出，不能把候选分数称为匹配概率。单据可能晚到；每次新记录到达会影响未完成发票，但不静默改写已完成记录。
