# 架构

## 分层

```text
frontend/                 中文工作台与历史查询
app/api/                  HTTP、认证、范围和错误映射
app/services/             用例编排与事务边界
app/domain/               状态、DTO 和确定性规则
app/infra/                PostgreSQL、MinIO、MinerU、模型适配器
app/workers/              抽取与工作台后台轮询
migrations/               数据库结构的唯一演进记录
spec/                     简化工作台的冻结契约
```

API 不保存进程内业务状态。PostgreSQL 是任务、修订、预览、确认和审计记录的事实源；
MinIO 保存原件与解析产物。Worker 可独立重启，通过租约、fencing、幂等键和数据库锁
避免重复提交或过期进程覆盖新结果。

## 两条输入路径

- 上传文件：原件 → Extraction Task/Run → MinerU → 结构化模型 → 确定性校验 → 修订。
- TapTouch Receiving：带范围的机器凭据 → 单调版本和幂等导入 → 权威修订。

两条路径进入同一工作台，但信任来源保持可见。模型输出不是财务事实；正式结果只由
当前输入、确定性规则和用户确认共同产生。

结构化供应商允许名称未知但保留有证据的 ABN 和地址。通用单据标题不会充当供应商
名称；身份匹配仍优先使用双方 ABN，缺少可靠身份时保持未核验并交给用户校正。

## 工作台数据

核心表族包括：抽取任务与运行、草稿与证据、不可变版本、旧核对/Case、实验评测，
以及 `ws_scope_state`、`ws_documents`、`ws_revisions`、`ws_previews`、
`ws_confirmations`、`ws_claims`、`ws_actions`、`ws_idempotency`。字段和约束以
`database_models.py` 与 Alembic migration 为准。

工作台使用独立 `ws_` 表，不改写旧批准版本和旧核对快照。确认、重开、作废和来源
变化都留下追加式 Action。预览可以失效和重算，Confirmation 不可覆盖。

## 接口与权限

日常工作台使用 `/api/workspace`；旧上传、审核、核对和 Case 接口在工作台启用后只读。
浏览器继续使用 HttpOnly Session，写请求保留 CSRF/Origin 门禁；对象按配置的
tenant/store 范围查询，范围外返回 404。TapTouch 机器接口使用独立 Bearer 凭据。

完整请求响应查看运行中的 `/docs` 和 [冻结契约](../spec/03-contracts.md)，避免在这里
维护第二份全量 API 清单。

## 一致性边界

- 上传对象写入失败会补偿，避免数据库或对象存储留下单边记录。
- 确认会重新读取当前修订、候选占用和 scope generation，不信任浏览器旧预览。
- `expected_revision`、幂等键和事务锁共同处理双击、重试和并发操作。
- 未知值不会用零代替；异常不会被“成功”状态掩盖。
- 原件和 CSV 下载必须先通过当前用户与工作区授权。

这些边界比框架名称更重要。当前 Python/FastAPI/PostgreSQL 结构已经满足需求，不因
外部 .NET 示例仓库而重构技术栈。
