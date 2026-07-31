# PyCharm 断点调试业务流程

这份练习用于真正理解 Invoice 与 Receive Note 核对，而不是先陷入数据库、
网络和模型配置。入口是项目根目录的 `demo_business_flow.py`，它仅调用领域模型
和纯业务规则。

## 运行前准备

在 PyCharm 中：

1. 打开 `E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation`；
2. 选择解释器 `.venv\Scripts\python.exe`；
3. 打开 `demo_business_flow.py`；
4. 右键文件，选择 **Debug 'demo_business_flow'**。

该脚本不读取 `.env`，不会连接真实基础设施，也不会产生模型费用。

## 演示案例

案例是一家澳洲披萨门店的分批收货：

| 单据 | 面粉 | 奶酪 | PO |
|---|---:|---:|---|
| Invoice | 10 箱 | 6 箱 | PO-SYD-1042 |
| Receive Note A | 6 箱 | 3 箱 | PO-SYD-1042 |
| Receive Note B | 4 箱 | 2 箱 | PO-SYD-1042 |
| 收货合计 | 10 箱 | 5 箱 | PO-SYD-1042 |

预期结果：

- 两张 Receive Note 都会成为高分候选；
- 面粉数量完全一致；
- 奶酪少收 1 箱；
- 最终 `requires_review=True`。

这证明“可能属于同一采购关系”和“数量金额完全相符”是两个不同问题。

## 第一组断点：领域模型

在 `demo_business_flow.build_demo_documents` 返回前设置断点，观察：

- `invoice.document_type` 自动固定为 `invoice`；
- `receive_notes[0].document_type` 自动固定为 `receive_note`；
- 金额与数量是 `Decimal`，不是二进制浮点数；
- 未知价格应是 `None`，不是 `0`。

然后尝试在 Debug Console 执行：

```python
invoice.model_dump(mode="json")
sum(note.items[0].quantity for note in receive_notes)
```

面试解释：Pydantic 模型是模型输出、人工审核和确定性规则之间的 Schema 边界。

## 第二组断点：候选匹配

在 `app/services/candidate_matching_service.py` 的 `assess_candidate` 设置断点，
逐步观察：

- `purchase_order_match` 提供 +40；
- supplier、location、currency、date 分别贡献可解释信号；
- item overlap 使用 SKU，缺少 SKU 才退化到描述；
- `score` 是人工配置的启发式分数，不是概率；
- PO 或币种明确冲突时，高总分也不能得到推荐。

重点观察：

```python
signals
score
bounded_score
has_blocking_conflict
```

面试解释：系统推荐候选，但不自动建立财务关系。审核人员仍需选择实际参与核对
的 Receive Notes。

## 第三组断点：一对多聚合

在 `app/services/reconciliation_service.py` 的 `_aggregate` 设置断点。

第一次调用聚合 Invoice 行；第二次调用聚合两张 Receive Notes 的全部商品行。
观察 `grouped` 和 `result`：

```text
sku:flour125 -> quantity 10
sku:cheese2  -> quantity 5
```

面试解释：不能把每张分批收货单分别与整张 Invoice 比较，否则每一批都会看起来
少收。必须先确认业务关系，再对所有相关收货单按商品聚合。

## 第四组断点：差异分类

在 `_classify` 设置断点：

- 面粉行进入 `exact`；
- 奶酪行的数量差为 1，超过默认 quantity tolerance 0；
- 奶酪行进入 `mismatch`，原因包含 `Quantity differs`。

继续到 `reconcile` 返回前，观察：

```python
comparisons
purchase_order_match
ReconciliationSummary
```

最终 `requires_review=True`，但系统不会自动拒付。它只提供需要人工处理的确定性
差异证据。

## 与完整系统的关系

这个脚本从“批准版本”之后开始。完整链路仍然是：

```text
上传原件
  -> MinerU 解析
  -> LLM 结构化
  -> Pydantic Schema
  -> 确定性 Validation
  -> 人工修订与批准
  -> Candidate Matching
  -> Reconciliation
```

纯脚本有三个用途：

- 学习规则时隔离外部依赖；
- 面试现场快速证明一对多算法；
- 规则回归测试，不消耗 MinerU/LLM API。

它不能证明 OCR、模型准确率、数据库事务或 Worker 调度已经正确运行。那些能力
分别由集成测试、评测集和完整 UI 演示覆盖。

## 推荐面试讲解顺序

1. 先运行脚本，展示最后的两条商品差异；
2. 回到 Candidate Signal，说明为什么 PO 不是唯一匹配条件；
3. 展开 `_aggregate`，说明一对多分批收货；
4. 展开 `_classify`，说明规则可重复、可审计；
5. 最后说明完整系统如何用人工批准版本保护这个确定性核心。

建议控制在 3–5 分钟。先讲业务问题和风险边界，再说明 Python、Pydantic、
PostgreSQL、MinerU 和 LLM 分别承担了什么职责。
