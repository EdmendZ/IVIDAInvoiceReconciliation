# 产品定位：Taptouch Back Office 的收货对账扩展

## 一句话定位

本项目是面向 IVIDA/Taptouch Back Office 的 **Invoice 与 Receiving 对账原型**：
它把供应商要求付款的 Invoice，与门店在 Taptouch 中已经确认的收货事实进行
候选匹配和确定性差异核对。

## 两条数据入口

系统不应把所有业务数据都强行送进 OCR/LLM。

| 输入 | 可信路径 | 原因 |
|---|---|---|
| 外部供应商 Invoice | 上传 → MinerU/LLM → 人工审核 | 发票格式不统一，模型结果需要人确认 |
| Taptouch Receiving | 结构化集成 → 权威版本 | 收货已经在上游业务系统中形成结构化事实 |
| 外部 Receive Note 文件 | 上传 → MinerU/LLM → 人工审核 | 兼容尚未进入 Taptouch 的外部文件 |

因此，Taptouch Receiving 不创建虚假的 Extraction Task、Draft、Reviewer 或
Review Action。它通过上游身份、单调版本号和作废状态建立可信度；上传单据则
继续通过人工批准建立可信度。两条路径最终汇合到同一张不可变
`document_versions` 表，再进入候选匹配和对账。

## IVIDA 需求与 Zeemart 参考的边界

IVIDA/Taptouch 的产品场景是本项目的需求来源；Zeemart 只用于参考采购单据自动化
产品常见的交互方式。项目不会因为参考产品存在某项功能，就假设 Taptouch 也有
相同流程或数据契约。

当前集成字段是本原型定义的稳定防腐层，不声称等同于尚未获得的真实 Taptouch
生产 API。接入真实 API 时，应在适配器层完成字段转换，而不是改变内部
`Invoice`、`ReceiveNote` 和对账规则。

## 外部 invoice-processor 仓库的参考边界

外部 MatchFlow/invoice-processor 只用于参考两类表达：列表的搜索、筛选和紧凑状态信息，
以及详情页集中呈现原件、抽取字段、匹配结果和差异；其
Controller/Application/Repository/Infrastructure 分层也用于核对本项目现有分层方向。
当前工作台和详情页已经覆盖这些信息结构，因此不为参考仓库重构架构。

不采用该仓库的 PO 业务对象、手动 Start Match、前端模拟进度、三字段百分比置信度、
缺失值补零、localStorage JWT、同步阻塞 OCR 上传和硬编码 Dashboard 指标。本项目继续
使用 Invoice 与 Receive Note 任意顺序到达、后台自动处理、行级保守比对、HttpOnly
Session 和一次人工确认。

## 明确不做什么

- 不在本项目重新实现完整采购订单（PO）系统；PO 号只是可选匹配信号。
- 不直接付款、不连接银行、不替代会计审批。
- 不让 LLM 自动批准财务事实。
- 第一阶段不实现完整多租户权限、Webhook、凭据轮换或工作流模式切换。
- 不把已作废的上游收货记录继续用于新对账。

## 判断成功的标准

第一阶段成功不是“页面更多”，而是以下业务闭环成立：

1. Taptouch 可重复发送同一收货版本而不产生重复数据；
2. 新版本保留旧版本审计历史，较旧版本被拒绝；
3. 最新版本作废后，旧有效版本不再参与候选匹配；
4. 用户能看出候选来自 Taptouch 还是人工上传；
5. 对账仍只使用确定性规则，不因结构化导入而改变财务判定。

## 简化工作台闭环

Invoice 与 Receive Note 先后到达都进入同一工作台。Worker 在来源 ready 后自动生成匹配
预览，系统保留等待、待核实和已完成状态；用户不需要启动提取或匹配按钮。确认写入当时
输入的不可变快照，重开会释放收货占用并以新确认记录重新核对。
