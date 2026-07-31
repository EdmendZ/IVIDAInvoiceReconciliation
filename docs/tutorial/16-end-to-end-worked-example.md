# 完整业务算例：一张发票、两次收货如何核对

## 场景

Sydney 的 Harbour Slice Pizza 向 Southern Cross Foodservice 采购原料，采购
订单号为 `PO-SYD-1042`。供应商开出一张 Invoice，门店分两次收货。

## 原始业务事实

### Invoice

| SKU | 商品 | 数量 | 单价 | 金额 |
|---|---|---:|---:|---:|
| FLOUR-12.5 | Pizza flour 12.5 kg | 8 | 22.50 | 180.00 |
| TOMATO-6 | Italian tomato base | 4 | 31.20 | 124.80 |
| OLIVE-3 | Sliced black olives | 2 | 19.80 | 39.60 |

小计 344.40，GST 34.44，总额 378.84 AUD。

### Receive Note 1

| SKU | 数量 |
|---|---:|
| FLOUR-12.5 | 5 |
| TOMATO-6 | 4 |

### Receive Note 2

| SKU | 数量 |
|---|---:|
| FLOUR-12.5 | 3 |
| OLIVE-3 | 2 |

## 第一步：上传

三份原件分别创建三个 ExtractionTask。Task 保存文件类型、SHA-256 和 MinIO
对象键。此时还没有模型结果。

## 第二步：创建 Run

每个 Task 创建一个 queued ExtractionRun。Run 记录：

- 当前 Provider；
- 状态和调度时间；
- 后续的远端 Job ID；
- Token、延迟和模型版本；
- 失败或取消信息。

## 第三步：MinerU 解析

Worker 原子领取 Run，将原件提交 MinerU，然后保存 remote_job_id。轮询成功后：

- ZIP 进入 MinIO；
- Markdown、blocks、tables 进入 PostgreSQL；
- Run 进入 normalizing。

## 第四步：LLM 归一化

LLM 将三个不同版面的文档都转换到同一 Schema。假设 Invoice 出现两个问题：

1. 页面水印被当成 supplier.name；
2. 商品行号没有抽取。

商品 SKU、数量和金额仍被正确识别。Schema Valid 只能说明数据结构合法，不会
自动发现供应商名称语义错误。

## 第五步：Validation

规则计算：

$$
180.00 + 124.80 + 39.60 = 344.40
$$

$$
344.40 + 34.44 = 378.84
$$

因此金额规则通过。供应商名称问题不属于当前确定性算术规则，需要 Evidence
和人工审核发现。

## 第六步：人工审核

审核人员：

1. 展开 Model Run，确认模型和 Prompt；
2. 将 supplier.name 的 Evidence 与原件核对；
3. 修正名称，创建 Version 2；
4. 确认文档类型为 Invoice；
5. 批准 Version 2。

两张 Receive Notes 也分别核对并批准。

## 第七步：候选推荐

系统为每张已批准 Receive Note 生成 Signal：

- PO 匹配：+40；
- Supplier 匹配：+20；
- Location 匹配：+10；
- AUD 匹配：+10；
- 日期接近：+10；
- 商品有重叠：按比例加分。

两张收货单都会成为 recommended。这个分数帮助选择，不代表统计概率。

## 第八步：一对多聚合

系统先合并两张 Receive Notes：

| SKU | RN 1 | RN 2 | 聚合数量 | Invoice 数量 |
|---|---:|---:|---:|---:|
| FLOUR-12.5 | 5 | 3 | 8 | 8 |
| TOMATO-6 | 4 | 0 | 4 | 4 |
| OLIVE-3 | 0 | 2 | 2 | 2 |

三行数量完全匹配。

如果错误地逐张比较：

- RN 1 会被误判 FLOUR 少 3、OLIVE 缺失；
- RN 2 会被误判 FLOUR 少 5、TOMATO 缺失。

这就是“一对多先聚合”的业务必要性。

## 第九步：保存核对结果

一个事务保存：

- Reconciliation 头；
- Invoice Version ID；
- 两个 Receive Note Version ID；
- 完整 Result JSON；
- 每一条商品行结果；
- 操作用户和时间。

结果引用不可变批准版本，所以以后可以复算当时为什么得到该结论。

## 变体：短收

如果 RN 2 的 FLOUR 只有 2：

| SKU | Invoice | 聚合收货 | 差异 | 状态 |
|---|---:|---:|---:|---|
| FLOUR-12.5 | 8 | 7 | 1 | mismatch |

默认数量容差为 0，因此 `requires_review=true`。

## 变体：两分钱内金额差

如果聚合金额与 Invoice 相差 0.01，而金额容差为 0.02：

- 状态为 within_tolerance；
- 差异仍被保存；
- 默认不因这一行单独触发 requires_review。

## 从算例定位代码

| 步骤 | 源码 |
|---|---|
| 上传 | `document_upload_service.py` |
| 排队 | `extraction_service.py` |
| 解析/归一化 | `extraction_worker.py` |
| 算术验证 | `validation_service.py` |
| 人工版本 | `review_service.py` |
| 候选 | `candidate_matching_service.py` |
| 聚合核对 | `reconciliation_service.py` |
| 结果事务 | `postgres_reconciliation_repository.py` |

## 复习总结

这个例子串起了项目的核心思想：

- 模型可以有语义错误，即使 Schema 和算术都合法；
- Evidence 与人工审核补足规则无法判断的内容；
- 批准版本隔离机器输出与可信业务输入；
- 分批收货必须先聚合；
- 最终核对与持久化不依赖 LLM。
