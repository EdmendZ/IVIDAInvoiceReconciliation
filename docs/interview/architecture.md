# 架构与责任边界

```text
Browser / React
      |
      v
FastAPI ──────────────> PostgreSQL
  |                     tasks, runs, drafts,
  |                     versions, actions, results
  |
  +───────────────────> MinIO
  |                     immutable source files
  |
  v
Extraction Worker
  |
  +──> MinerU API ──> Markdown / tables / blocks
  |
  +──> LLM API ─────> normalized JSON + evidence
  |
  +──> Pydantic + deterministic validation
                         |
                         v
                    Human review
                         |
                         v
               Deterministic reconciliation
```

## 为什么不让 LLM 直接核对

LLM 擅长从多样化单据中理解字段，但金额计算、容差、状态转换和审批边界需要
可重复、可测试。项目因此采用“LLM 抽取 + 规则决策 + 人工闸门”。

## 为什么使用 PostgreSQL 轮询

本机 Pilot 只有一个 Worker，PostgreSQL 已经承担任务持久化和审计。此阶段
增加 Redis/RabbitMQ 会增加启动、演示和故障恢复复杂度，却没有得到足够收益。
状态领取使用条件更新，API 重启不会丢失排队任务。

多 Worker、长任务吞吐或独立弹性伸缩出现后，再引入消息代理和租约 fencing。

## 数据边界

- PostgreSQL：业务状态、版本、审核动作、模型运行元数据。
- MinIO：原始 PDF/图片和解析产物。
- 评测目录：Git 忽略的合成原件、Gold、缓存与结果。
- Git：代码、Prompt 模板、评测器和不含隐私的说明。

## 已实现

- 持久化异步任务、Worker 心跳和协作式取消；
- MinerU + LLM 结构化抽取；
- Schema/财务校验和证据化人工审核；
- 不可变批准版本和一对多对账；
- 模型与 Prompt 溯源；
- 缓存、失败隔离和模型对比评测框架；
- 一键本机启动。

## 明确未实现

- 真实客户数据上的统计结论；
- 多租户与细粒度数据权限；
- 四眼审批和完整财务合规；
- 多 Worker fencing、消息代理与高可用；
- 恶意文件扫描、KMS、保留策略和灾备；
- 自动付款或无人审批。
