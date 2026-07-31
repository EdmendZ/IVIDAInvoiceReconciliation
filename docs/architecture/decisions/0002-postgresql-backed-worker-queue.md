# ADR 0002：Pilot 使用 PostgreSQL 持久化队列

- 状态：Accepted for Pilot
- 日期：2026-07-31

## 背景

MinerU/LLM 任务跨秒执行，不能绑定 FastAPI 请求进程。项目已有 PostgreSQL，
当前只需单 Worker 本机演示。

## 决策

ExtractionRun 保存状态、下次执行时间和租约。Worker 使用行锁与
`SKIP LOCKED` 领取到期任务。

## 结果

优点：

- API/Worker 重启不丢任务；
- 不增加 Redis/RabbitMQ 运维；
- 状态、重试、成本和审计位于同一数据库；
- 测试和本机启动简单。

代价与边界：

- PostgreSQL 同时承担业务与队列负载；
- 没有可靠消息推送；
- 当前没有租约续期和 fencing token；
- 不声称支持多 Worker 高吞吐。

## 重新评估条件

出现多 Worker、吞吐积压、独立弹性、严格投递语义或业务库负载冲突时，引入
消息代理并设计 outbox/idempotency/fencing。
