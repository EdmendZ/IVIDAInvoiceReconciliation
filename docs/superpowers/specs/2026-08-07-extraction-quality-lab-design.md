# Extraction Quality Lab 设计

## 1. 背景与目标

IVIDA 已经具备 MinerU 解析、OpenAI-compatible 结构化归一化、人工审核、
合成 Gold 数据集和基础抽取评测能力。当前评测可以计算 Schema 通过率、字段
准确率、行项目 F1、Evidence Coverage、延迟和成本，但“实验配置、错误分析、
人工反馈和模型升级决策”仍是彼此分离的操作。

本设计增加 **Extraction Quality Lab（抽取质量实验室）**，把模型迭代变成一条
可复现、可解释、可审计的质量闭环：

1. 使用真实 MinerU 和结构化模型运行版本化实验；
2. 保存模型、Prompt、Parser、Schema、参数和数据集版本；
3. 对预测结果执行 Gold 对比和错误切片；
4. 将人工审核修改沉淀为待确认的反馈候选；
5. 使用明确门槛比较 baseline 与 candidate；
6. 输出推荐、拒绝或证据不足的结构化结论。

该能力面向大模型应用工程岗位的项目展示，重点证明系统能够评测和治理模型，
而不只是调用一次模型 API。

## 2. 范围

### 2.1 本阶段包含

- 不可变的实验定义和可追溯的实验运行；
- 真实 MinerU、真实结构化模型和现有 MinerU 缓存；
- 文档级结果、汇总指标和错误切片；
- baseline/candidate 同数据集对比；
- 从人工审核动作生成 Feedback Candidate；
- 人工确认反馈类型和是否可以进入 Gold；
- 基于质量、关键回归、延迟和成本的 Promotion Decision；
- 轻量实验页面和可导出的 JSON/Markdown 报告。

### 2.2 本阶段不包含

- 自动训练、微调或在线学习；
- 自动修改生产模型配置或自动发布模型；
- embedding 商品匹配；
- Agent 自动调查或处置财务差异；
- 通用生产级 MLOps 平台；
- 未经人工确认就把 Reviewer 修改写入 Gold。

## 3. 业务原则

### 3.1 实验结果必须可复现

同名 variant 不能隐藏配置变化。每次实验必须绑定数据集版本及样本哈希、Parser、
Normalizer、Prompt、Schema 和影响输出的模型参数。报告必须能回答“使用什么配置、
在什么数据上、得到什么结果”。

### 3.2 失败必须进入分母

MinerU、网络、模型、JSON 或 Schema 失败都属于实验结果。单文档失败不能终止
整批运行，也不能从统计中消失，以免产生幸存者偏差。

### 3.3 人工修改不天然等于 Gold

Reviewer 可能修复模型错误，也可能统一缩写、补充内部信息或误操作。人工修改先
形成 Feedback Candidate，必须分类并确认后才能扩充评测 Gold。

### 3.4 推荐不等于自动上线

Promotion Decision 只给出可解释的推荐结论。系统不得自动修改 `.env`、默认模型
或部署配置。模型切换仍是显式的人工发布决定。

## 4. 领域对象

### 4.1 ExperimentDefinition

描述一次实验的不可变配置：

- `experiment_id` 和可读名称；
- baseline 或 candidate 角色；
- dataset 版本、manifest 哈希和样本哈希；
- Parser provider/model/version；
- Normalizer provider/model；
- Prompt version 和 Schema version；
- temperature、最大输出 Token 等关键参数；
- Schema、字段、行项目、Evidence、延迟和成本门槛；
- 创建人和创建时间。

实验定义创建后不可覆盖。调整任一影响结果的字段必须创建新定义。

### 4.2 EvaluationRun

描述一次真实执行：

- `queued`、`running`、`completed`、`failed` 或 `cancelled` 状态；
- 实验定义 ID、开始时间和结束时间；
- 每份文档的预测、Gold 差异、Evidence、失败阶段和错误码；
- Token、延迟、成本和 Parser 缓存命中；
- 汇总指标与错误切片；
- 运行级安全错误摘要。

运行中断后可以复用已验证的 MinerU 缓存，但未完成预测不能标记为成功。

### 4.3 FeedbackCandidate

从 `DocumentDraft → DocumentVersion` 和 `ReviewAction` 提取：

- Task、Draft、Version、Run 和字段路径；
- 模型原值与人工新值；
- 文档类型、供应商、模型和 Prompt 版本；
- 修改人和修改时间；
- 反馈分类、确认人和确认时间；
- 是否允许进入 Gold。

反馈分类固定为：

- `model_error`：模型抽取或归一化错误；
- `acceptable_variant`：表达不同但业务等价；
- `reviewer_correction_error`：人工修订错误；
- `business_context_update`：新增模型不可从原件推断的业务信息。

只有经过人工确认的 `model_error` 可以进入 Gold 候选集。Gold 变更仍需保存数据集
版本和变更来源，不能原地静默覆盖。

### 4.4 PromotionDecision

保存一次 baseline/candidate 决策：

- 两个实验定义及运行 ID；
- 数据集版本一致性；
- 每个硬门槛和质量门槛的结果；
- 关键回归和已修复错误切片；
- `recommended`、`rejected` 或 `inconclusive` 结论；
- 结构化理由、决策人和时间。

## 5. 数据流

主实验链路：

```text
合成或已批准脱敏文档
  → ExperimentDefinition
  → MinerU 解析与缓存
  → Normalizer 预测
  → Gold 对比
  → 错误切片与汇总
  → baseline/candidate Promotion Decision
```

人工反馈链路：

```text
DocumentDraft
  → 人工 DocumentVersion / ReviewAction
  → FeedbackCandidate
  → 人工分类和确认
  → 新版本评测数据集
  → 后续实验
```

反馈链路不能绕过确认步骤，也不能直接触发模型配置变化。

## 6. 指标与错误切片

### 6.1 硬门槛

- Schema Valid Rate 为 100%；
- Invoice/Receive Note 类型识别不退化；
- Invoice Number、Purchase Order Number、币种和商品行等关键字段无新增严重回归；
- 所有失败文档进入分母；
- 已配置价格时，单文档成本不超过实验门槛；
- baseline 与 candidate 使用相同数据集版本和样本集合。

硬门槛失败时不得输出 `recommended`。

### 6.2 质量门槛

- Field Micro Accuracy 不低于 baseline；
- Line-item F1 不低于 baseline；
- Evidence Coverage 不低于 baseline；
- candidate 至少修复一个已知错误切片，或在预先声明的目标指标上产生明确提升。

不使用单一综合分数掩盖关键字段退化。

### 6.3 观察指标

- P50/P95 延迟；
- 输入、输出 Token；
- 平均成本和总成本；
- MinerU 缓存命中率；
- 各文档类型、字段组、错误类型和业务场景的错误分布。

成本价格未配置时保持 `unknown`，不得当作零成本。

### 6.4 第一版切片维度

- 文档类型：Invoice、Receive Note；
- 字段组：身份、采购、金额、商品行；
- 错误类型：缺失、错误值、额外幻觉值、Schema 失败、Evidence 缺失；
- 业务场景：完全匹配、分批收货、短收、价格差异、发票独有、收货单独有、
  容差和采购订单冲突。

## 7. Promotion 规则

决策顺序固定：

1. 验证运行完整性和数据集一致性；
2. 检查 Schema、关键字段和成本硬门槛；
3. 检查字段、行项目和 Evidence 质量回归；
4. 检查预先声明的目标错误切片是否改善；
5. 记录延迟和成本取舍；
6. 生成结论和逐条理由。

结论定义：

- `recommended`：全部硬门槛通过，且存在可解释的质量提升；
- `rejected`：硬门槛失败或存在关键回归；
- `inconclusive`：样本不一致、样本不足、运行不完整、成本未知且成本是硬门槛，
  或差异不足以支持结论。

Promotion 计算出现异常时，结论只能是 `inconclusive`，不能默认放行。

## 8. 代码边界

建议新增以下聚焦模块：

- `app/experiments/domain.py`：实验、运行、反馈和决策的数据契约；
- `app/experiments/runner.py`：实验编排，调用现有 Parser、Normalizer 和评测器；
- `app/experiments/slicing.py`：错误分类与切片统计；
- `app/experiments/feedback.py`：审核事实到 Feedback Candidate 的转换；
- `app/experiments/promotion.py`：纯门禁和对比规则；
- `app/experiments/reporting.py`：JSON/Markdown 报告。

现有 `app/evaluation/runner.py` 继续负责文档执行和原始结果汇总，不承载实验定义、
反馈治理或发布决策。`comparison.py` 保持纯比较逻辑。`ReviewService` 只记录审核
事实，不决定 Gold 资格。Repository 只负责原子持久化，不包含排名规则。

前端新增独立的轻量实验区域，展示：

- 实验列表和运行状态；
- baseline/candidate 指标对照；
- 关键回归和错误切片；
- Promotion 结论与理由；
- 待确认 Feedback Candidates。

新页面不并入已经较大的 `CaseDetailPage.tsx` 或 `ReviewDocumentPage.tsx`。

## 9. 定向代码改进

- `CaseDetailPage.tsx` 已承担状态摘要、Item 编辑、审批和审计时间线，后续可独立
  拆分，但不与本功能放入同一个改动批次；
- `ReconciliationCaseService` 虽然较长，但状态门禁集中且已有测试，本阶段不按
  行数强拆；后续可提取纯状态转换策略；
- `database_models.py` 可按领域拆分，但涉及较大结构迁移，本阶段暂缓；
- 新实验能力从开始就按职责拆分，避免继续扩大现有评测 Runner 和审核 Service。

## 10. 异常处理

- 每份文档独立捕获 MinerU、网络、模型、JSON、Schema 和指标错误；
- 明确区分临时错误与永久错误，只有临时错误可按配置重试；
- 保存重试次数和最终稳定错误码，不暴露凭据或完整敏感模型响应；
- 单文档失败后继续后续文档，并将失败计入汇总；
- baseline/candidate 数据集不一致时拒绝比较；
- 取消或进程中断不产生伪完成状态；
- 报告生成失败不改变原始运行事实；
- Promotion 失败保持安全关闭，不能输出推荐。

## 11. 测试策略

### 11.1 单元测试

- 实验定义不可变性和完整溯源字段；
- 错误分类与切片统计；
- Feedback Candidate 四类分类和 Gold 资格；
- Promotion 硬门槛、质量回归和三种结论；
- 成本未知、关键字段回归和数据集不一致场景。

### 11.2 契约与集成测试

- Fake Parser/Normalizer 的完整实验链路；
- 单文档失败不终止整批运行；
- 运行结果能够离线复算；
- 审核动作能够生成可追溯 Feedback Candidate；
- 未确认反馈不能进入 Gold；
- Repository 原子保存运行和决策事实。

### 11.3 真实评测

- 先用一份文档调用真实 MinerU 和模型做冒烟；
- 再使用全部 17 份合成文档执行 baseline/candidate 对比；
- 注入超时、非法 JSON、Schema 错误、部分失败和未知成本；
- 保存运行配置和报告，使面试演示可以复查而不是依赖口头结论。

### 11.4 前端测试

- 正确显示质量提升和关键回归；
- 未知成本不能显示为零；
- 失败、取消和 `inconclusive` 状态具有明确解释；
- 未确认 Feedback Candidate 不能显示为 Gold；
- Promotion 理由与后端结构化结果一致。

## 12. 验收标准

第一阶段完成必须满足：

1. 能创建两个配置不同且溯源完整的实验定义；
2. 能在同一数据集上运行 baseline 和 candidate；
3. 报告能定位到具体文档、字段、错误类型和业务场景；
4. 人工字段修改能够生成 Feedback Candidate；
5. 未经确认的反馈不能进入 Gold；
6. Promotion Decision 能解释每个门槛的通过或失败；
7. 全部 17 份合成文档运行时，单份失败不会使统计失真；
8. 真实 API 冒烟和缓存复用均有可验证记录；
9. 面试中能够在 5–8 分钟内演示真实实验、错误分析和版本决策；
10. 文档明确区分实验推荐与人工发布，不能声称已实现自动模型上线。

## 13. 面试证据链

完成后，项目应能够用以下顺序说明：

1. 为什么单元测试不能证明模型效果；
2. 如何构造 Gold、隔离 MinerU 缓存并控制实验变量；
3. 为什么失败必须进入分母；
4. 如何从总体指标下钻到字段和业务场景；
5. 为什么人工修改需要再次确认才能成为 Gold；
6. 如何用质量、成本和延迟门槛比较模型或 Prompt；
7. 为什么推荐决策不应自动修改生产配置。

核心项目表述为：

> 我没有凭感觉调整 Prompt，而是通过版本化实验、错误切片和人工反馈衡量改动，
> 并使用可解释的质量与成本门禁控制模型升级决策。
