# 源码注释与阅读地图

这份文档解决两个问题：

1. 项目中的注释应该解释什么，避免注释退化成代码的中文复述；
2. 为第一次阅读源码的人提供一条能跑通业务思路的路径。

## 注释分为四层

### 模块注释：解释边界

模块开头说明这组代码在系统里的位置、输入输出和不负责的事情。例如
`app/api/dependencies.py` 是依赖装配点，它把 PostgreSQL、MinIO 和业务服务
接起来，但不承载业务规则。

### 类注释：解释业务概念

类注释重点回答“为什么不能和另一个对象合并”。本项目最重要的区分包括：

| 概念 | 含义 | 不能合并的原因 |
|---|---|---|
| Task | 一份上传文件的生命周期 | 重试不会产生新文件 |
| Run | 一次具体的模型处理尝试 | 每次尝试的模型、成本、错误不同 |
| Draft | 模型产出的可编辑候选数据 | 尚未得到人工背书 |
| Version | 一次不可变业务快照 | 必须保留人工修订与审批轨迹 |
| Candidate | 可能属于同一采购关系的推荐 | 推荐不等于确认 |
| Reconciliation | 对已选文档执行的确定性核对 | 结果必须可重复、可审计 |

### 方法注释：解释契约和副作用

公共方法说明调用前提、关键副作用和失败语义。例如：

- 上传方法同时写 MinIO 和 PostgreSQL，第二步失败时需要清理对象；
- 保存审核修改会创建新版本，而不是覆盖旧版本；
- 批准方法只接受 Draft，且有 blocking issue 时拒绝放行；
- 对账入口只读取人工批准的 Invoice 和 Receive Note。

### 行内注释：解释“不直观但必要”的实现

行内注释只放在容易误删或误改的位置，例如：

- 上传读取 `max_bytes + 1` 是为了区分“刚好达到上限”和“超过上限”；
- API 进程使用禁用的模型 Provider，因为实际调用由 Worker 承担；
- 前端实时校验需要防抖和取消旧请求，避免旧响应覆盖新内容；
- Candidate Matching 只排序，不能自动确认业务关系。

不建议添加这类注释：

```python
# 把状态设置为 failed
status = "failed"
```

它没有提供代码之外的信息。更有价值的注释应说明为什么失败状态仍保留原件、
是否允许重试，以及它与 Run/Task 状态的关系。

## 推荐源码阅读顺序

### 第一遍：走通主业务

1. `app/services/document_upload_service.py`
2. `app/services/extraction_service.py`
3. `app/workers/extraction_worker.py`
4. `app/services/review_service.py`
5. `app/services/candidate_matching_service.py`
6. `app/services/reconciliation_application_service.py`
7. `app/services/reconciliation_service.py`

阅读目标不是记住每一行，而是回答：

- 原件、任务、运行结果和批准版本分别存在哪里？
- LLM 的不确定性在哪一层被拦截？
- 哪一步需要人工承担业务责任？
- 对账为什么使用规则而不是继续调用 LLM？

### 第二遍：理解端口与适配器

先读 `app/services/ports.py`，再挑选对应实现：

| Port | Adapter | 关注点 |
|---|---|---|
| ObjectStorage | `app/infra/minio_storage.py` | 原件和大附件不进入数据库 |
| Task/Run Repository | `app/infra/postgres_*repository.py` | 状态持久化和 Worker 抢占 |
| AsyncDocumentParser | `app/infra/mineru_parser.py` | 提交与轮询分离 |
| NormalizationProvider | `app/infra/openai_normalization_provider.py` | Schema、Prompt、成本与证据 |

这里体现依赖倒置：业务服务面向 Protocol 编程，外部供应商或数据库变化时，
核心用例不需要重写。

### 第三遍：从前端验证业务门禁

1. `frontend/src/upload/UploadPage.tsx`：上传和异步 Run 为什么分两步；
2. `frontend/src/review/ReviewDocumentPage.tsx`：实时校验、类型确认和不可变版本；
3. `frontend/src/reconcile/ReconciliationPage.tsx`：候选推荐与实际核对的区别；
4. `frontend/src/api/client.ts`：Cookie 会话和统一 401 行为。

前端禁用按钮只改善体验，不能当作安全边界。后端服务必须重复校验
`approved`、文档类型和阻断问题。

### 第四遍：理解模型实验

阅读顺序：

1. `app/evaluation/cache.py`
2. `app/evaluation/runner.py`
3. `app/evaluation/field_metrics.py`
4. `app/evaluation/comparison.py`
5. `app/evaluation/report.py`

MinerU 解析结果按原件哈希缓存，因此更换 Prompt 或归一化模型时不会重复支付
解析成本。每个失败样本仍进入指标，避免只统计成功样本造成幸存者偏差。方案
排序先施加单文档预算，再比较字段准确率、行项目 F1 和证据覆盖率。

## 面试时如何借助注释讲代码

可以从一个约束开始，而不是罗列技术栈：

> 财务单据中的模型输出不能直接成为付款依据，所以我把系统分为非确定性的
> 抽取区和确定性的控制区。模型只创建 Draft；规则校验和人工批准后才生成
> 不可变 Version；对账只读取批准版本。

然后打开以下三个文件作为证据：

- `app/workers/extraction_worker.py`：展示模型、证据、校验和草稿如何落库；
- `app/services/review_service.py`：展示审核门禁和不可变版本；
- `app/services/reconciliation_service.py`：展示数量、金额和容差规则可重复计算。

如果被追问为什么不用一个大模型端到端完成，可以回答：端到端模型更容易做出演
示，但难以稳定复算、解释差异和追责。本项目让模型负责感知与结构化，让规则和
人工负责财务决策，是根据风险边界做的拆分，不是单纯追求架构复杂度。

## 维护约束

新增核心模块或公开业务方法时，应同时满足：

- 模块或类注释说明职责边界；
- 非直观状态转换说明前置条件和副作用；
- 业务规则变化同步到 `docs/business` 或 `docs/ai`；
- API、数据库或运行方式变化同步到对应 reference/operations 文档；
- 不在注释中写密码、Token、真实客户数据或仅在当前机器成立的信息。

`tests/test_code_comment_coverage.py` 对一组核心教学文件执行最低注释覆盖检查。
它不是追求百分百 docstring，而是防止最重要的业务入口在重构后重新变成“只能
靠猜”的代码。
