# 候选匹配与一对多核对规则

## 两个阶段不要混淆

系统先回答：

> 哪些 Receive Notes 可能属于这张 Invoice？

然后才回答：

> 选择的这些 Receive Notes 与 Invoice 在商品、数量、价格和金额上是否一致？

前者是 Candidate Matching，后者是 Reconciliation。

## Candidate Matching

实现位置：`app/services/candidate_matching_service.py`

每张已批准 Receive Note 都会产生若干 Signal：

| Signal | 匹配权重 | 冲突权重 |
|---|---:|---:|
| 采购订单号 | +40 | -40 |
| 供应商 | +20 | -15 |
| 门店/收货地点 | +10 | -5 |
| 币种 | +10 | -25 |
| 日期接近 | +10 / +5 | 最低 -5 |
| 商品重叠 | 最高 +20 | 无重叠 -20 |
| 单据号完全相同 | — | -100 |

最终分数限制在 0–100：

- 75 以上：high；
- 45–74：medium；
- 低于 45：low；
- 60 以上且没有关键冲突，才标记 recommended。

关键冲突包括同号、采购订单不一致、币种不一致和无商品重叠。

### 为什么同号扣 100 分

Invoice 和 Receive Note 通常应有不同业务编号。两者编号完全相同，很可能是
同一文件被分别上传为两种类型，或模型分类错误。系统选择显式阻断推荐，让人
重新检查类型。

### 候选分数不是机器学习概率

它是可解释规则分，不是经过校准的“属于同一交易的 85% 概率”。面试时不能
把 score=85 说成统计概率。

## 商品匹配键

实现位置：`app/services/reconciliation_service.py`

规则：

1. 有 SKU 时使用标准化 SKU；
2. 没有 SKU 时使用标准化商品描述；
3. 标准化会转小写并移除非字母数字字符。

例如：

```text
"FLOUR-12.5" -> "sku:flour125"
"Pizza Flour 12.5 kg" -> "description:pizzaflour125kg"
```

这是一种轻量规则。它不能可靠处理同义词、供应商内部编码变化或包装规格语义，
所以生产演进可增加商品主数据映射或 embedding 候选，但最终仍需可解释门禁。

## 一对多聚合

所有选择的 Receive Notes 会先展开成一组商品行，再按 match key 聚合：

$$
Q_k^{recv} = \sum_{i=1}^{n} Q_{k,i}
$$

| 符号 | 含义 |
|---|---|
| $k$ | 标准化后的商品键 |
| $n$ | 参与核对的收货单数量 |
| $Q_{k,i}$ | 第 $i$ 张收货单中商品 $k$ 的数量 |
| $Q_k^{recv}$ | 商品 $k$ 的总收货数量 |

金额优先使用行金额；缺少行金额但存在单价时使用数量乘单价。

加权单价：

$$
P_k^{recv} = \frac{\sum_i Q_{k,i} P_{k,i}}{\sum_i Q_{k,i}}
$$

| 符号 | 含义 |
|---|---|
| $P_{k,i}$ | 第 $i$ 张收货单中商品 $k$ 的单价 |
| $P_k^{recv}$ | 按数量加权后的收货单价 |

如果某个参与行缺少单价，聚合单价保持未知，不伪造为 0。

## 差异状态

| 状态 | 含义 |
|---|---|
| exact | 数量、单价、金额完全一致 |
| within_tolerance | 存在差异，但都在容差内 |
| mismatch | 至少一个差异超过容差 |
| invoice_only | 发票有，收货记录没有 |
| receive_note_only | 收货记录有，发票没有 |

默认容差：

- 数量：0；
- 单价：AUD 0.01；
- 金额：AUD 0.02。

Validation 的文档级容差与 Reconciliation 容差不是同一概念：

- Validation 检查单张文档内部算术是否自洽；
- Reconciliation 比较不同业务单据之间是否一致。

## requires_review 如何决定

只要满足任一条件：

- 有 mismatch；
- 有 invoice_only；
- 有 receive_note_only；
- 采购订单明确不一致；
- 币种不一致；

结果就标记 `requires_review=true`。

`within_tolerance` 默认不触发 review，但仍保留差异数值供审计。

## 应用层门禁

`ReconciliationApplicationService.compare()` 在调用纯规则前：

1. 要求至少一张 Receive Note；
2. 验证 Invoice Version 已批准且类型正确；
3. 验证所有 Receive Note Version 已批准且类型正确；
4. Pydantic 重新构建领域对象；
5. 调用纯函数 `reconcile()`；
6. 保存参与版本 ID 和完整结果。

## 面试复习点

- Candidate Score 是解释性启发规则，不是概率；
- 推荐候选与执行核对是两个步骤；
- 一对多场景必须先聚合后比较；
- 缺失单价保持未知，不用 0 掩盖；
- 最终判断是确定性规则，可用单元测试完整覆盖。
