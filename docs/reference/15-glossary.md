# 项目术语表

## 为什么需要统一术语

这个项目同时包含财务业务、异步任务、大模型和数据治理。如果把 Task、Run、
Draft、Version 混用，代码能运行，团队仍会在需求和面试中产生误解。

## 业务单据

| 术语 | 中文理解 | 项目中的准确含义 |
|---|---|---|
| Invoice | 发票 | 供应商提出付款请求的商业单据 |
| Receive Note | 收货单 | 门店/采购方记录实际收货事实的单据 |
| Purchase Order / PO | 采购订单 | 采购关系标识，用于候选关联的重要信号 |
| Line Item | 商品行 | SKU、描述、数量、单价、税额和行金额 |
| Reconciliation | 核对/对账 | 将一张 Invoice 与一张或多张 Receive Notes 聚合比较 |
| Tolerance | 容差 | 允许的数量、单价或金额微小差异 |

当前不是 Invoice、PO、Receive Note 的三方对账，因为 PO 只作为编号/提示参与，
系统没有完整导入 PO 商品明细。

## 抽取生命周期

| 术语 | 含义 |
|---|---|
| ExtractionTask | 一份上传文件需要被处理的长期对象 |
| ExtractionRun | 对 Task 的一次具体处理尝试 |
| Remote Job | MinerU 侧异步任务 |
| ParseResult | MinerU 输出的 Markdown、blocks、tables |
| Normalization | 将解析文本映射到统一业务 Schema |
| DocumentDraft | 机器生成、尚未人工确认的结构化结果 |
| Evidence | 字段对应的页码与原文证据 |
| ValidationIssue | 文档内部规则发现的问题 |

## 人工治理

| 术语 | 含义 |
|---|---|
| DocumentVersion | 人工审核过程中产生的业务快照 |
| ReviewAction | 启动、修改、重分类、批准、驳回等追加式动作 |
| Draft Version | 可继续修改的人工版本 |
| Approved Version | 通过门禁且不可修改的可信核对输入 |
| Reclassification | 修正 Invoice/Receive Note 类型并创建新版本 |
| Human-in-the-loop | 人工实际参与证据核对和批准，不只是页面有按钮 |

## 候选与核对

| 术语 | 含义 |
|---|---|
| Candidate | 可能属于当前 Invoice 的 Receive Note Version |
| Signal | PO、供应商、币种、日期、商品重叠等可解释依据 |
| Score | 启发式规则分，不是概率 |
| Recommended | 分数达标且没有关键冲突 |
| Match Key | SKU 标准化值，缺失 SKU 时使用描述标准化值 |
| Exact | 所有被比较值完全一致 |
| Within Tolerance | 有差异但没有超过容差 |
| Mismatch | 至少一个差异超过容差 |
| Invoice Only | 商品只出现在发票 |
| Receive Note Only | 商品只出现在收货记录 |

## 异步与可靠性

| 术语 | 含义 |
|---|---|
| Worker | 独立于 API 的长任务处理进程 |
| Claim | Worker 原子领取一个到期 Run |
| Lease | 一段时间内 Run 属于某个 Worker 的处理权 |
| SKIP LOCKED | PostgreSQL 跳过其他事务已锁定的候选行 |
| Heartbeat | Worker 定期写入的存活时间 |
| Cooperative Cancellation | 在安全阶段边界停止本地处理 |
| Retryable Error | 可在有限退避后重试的外部错误 |
| Idempotent | 重复执行不会不断产生新副作用 |

Lease 不是完整 fencing。当前 Worker 不会为长阶段持续续租，也没有 fencing
token，所以不能据此声称可靠支持多 Worker 高并发。

## 模型与评测

| 术语 | 含义 |
|---|---|
| Parser | MinerU 这类版面/OCR/表格解析器 |
| Normalizer | 将解析结果转换为业务 Schema 的 LLM |
| Provider | 外部能力的可替换适配器 |
| JSON Mode | 要求模型返回可解析 JSON 的 API 能力 |
| Schema Valid | Pydantic 可以接受，不代表值一定正确 |
| Prompt Version | 系统 Prompt 和模板的内容指纹 |
| Gold | 人工确定的评测标准答案 |
| Field Micro Accuracy | 所有文档字段累计准确率 |
| Line-item F1 | 商品行匹配、缺失与多余的综合指标 |
| Evidence Coverage | Gold 字段中拥有 Evidence 的比例 |
| Provenance | 模型、Prompt、Token、延迟和成本来源记录 |

## 数据存储

| 术语 | 含义 |
|---|---|
| PostgreSQL | 关系、状态、版本、动作和核对结果 |
| MinIO | 原始文件和 MinerU ZIP 产物 |
| Bucket | MinIO 的项目级对象命名空间 |
| Object Key | Bucket 内的对象路径 |
| JSONB | PostgreSQL 中保存业务快照的 JSON 类型 |
| Migration | 可追踪的数据库 Schema 演进 |

## 面试中建议保持的用词

- 说“AI 辅助审核”，不要说“自动财务审批”；
- 说“候选规则分”，不要说“关联概率”；
- 说“单文档冒烟指标”，不要概括成“生产准确率”；
- 说“一张 Invoice 对多张 Receive Notes”，不要误称三方对账；
- 说“本机 Pilot”，不要声称高可用生产平台。
