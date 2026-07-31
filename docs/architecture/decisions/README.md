# Architecture Decision Records

ADR 记录“为什么这样设计”，而不仅是“当前代码长什么样”。当约束变化时，
可以新增 ADR 取代旧决策，不要静默重写历史原因。

| ADR | 决策 |
|---|---|
| [0001](0001-split-parser-and-normalizer.md) | Parser 与 Normalizer 分离 |
| [0002](0002-postgresql-backed-worker-queue.md) | Pilot 使用 PostgreSQL 持久化队列 |
| [0003](0003-human-approved-immutable-versions.md) | 只有人工批准不可变版本能核对 |
| [0004](0004-deterministic-reconciliation.md) | 最终差异使用确定性规则 |
| [0005](0005-postgresql-and-minio-storage.md) | PostgreSQL 与 MinIO 分工存储 |
