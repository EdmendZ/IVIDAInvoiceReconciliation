# 面试源码练习

建议先独立回答，再展开“参考思路”。目标不是背答案，而是训练从代码推导设计。

## 练习 1：为什么 claim_next 使用 SKIP LOCKED

定位：`app/infra/postgres_extraction_run_repository.py`

问题：

1. 两个 Worker 同时查询同一 queued Run 会怎样？
2. 行锁和 SKIP LOCKED 分别解决什么？
3. 为什么这还不等于完整多 Worker 安全？

参考思路：

- 行锁让被选中的记录在事务内不能被另一领取事务同时修改；
- SKIP LOCKED 让第二个 Worker 跳过锁定行，继续找下一条；
- 当前租约没有长阶段续期和 fencing token；
- 外部调用超过 lease 时仍可能出现重复处理风险。

## 练习 2：为什么 Task 和 Run 分离

定位：

- `app/domain/extraction_tasks.py`
- `app/domain/extraction_runs.py`

参考思路：

Task 表示文件级业务对象；Run 表示一次尝试。分离后可保存失败重试、模型版本、
成本和远端 Job，不覆盖原始上传身份。

## 练习 3：上传为什么先写 MinIO

定位：`DocumentUploadService.upload`

参考思路：

数据库 Task 必须指向一个真实存在的对象。先写对象，数据库失败时补偿删除。
反过来先写数据库，MinIO 失败会留下无法读取的 Task。两种都不是分布式事务，
生产还可用 outbox/repair job。

## 练习 4：为什么未知金额不能按 0

定位：

- `ValidationService.validate`
- `reconciliation_service._aggregate`

参考思路：

缺失代表未知，0 代表明确没有金额。混淆会产生虚假的 exact 或错误的 subtotal
mismatch。代码只在所有必要值都存在时进行相关比较。

## 练习 5：批准为什么用条件 UPDATE

定位：`PostgresReviewRepository.approve`

参考思路：

UPDATE 同时要求 version_id 匹配且 status=draft。并发重复批准时只有一个事务能
更新一行，另一个 rowcount 不为 1 并失败，避免已批准版本再次变化。

## 练习 6：Version 编号有什么并发风险

定位：`PostgresReviewRepository.create_version`

参考思路：

当前先查询 max(version_number) 再加一。两个并发事务可能计算同一编号，唯一
约束会让一个失败。Pilot 可接受；生产应使用行锁、序列、Serializable 或捕获
唯一冲突重试。

## 练习 7：为什么核对 Repository 一次 commit

定位：`PostgresReconciliationRepository.create`

参考思路：

头记录、参与 Receive Notes 和逐行结果构成一个聚合。任一插入失败应整体回滚，
不能出现“有头无行”或“行存在但缺少参与版本”。

## 练习 8：为什么 JSON Mode 后仍需 Pydantic

定位：`OpenAINormalizationProvider.normalize`

参考思路：

JSON Mode 只保证语法接近 JSON，不保证必填字段、Decimal 范围、document_type、
items 非空和嵌套结构满足业务要求。Pydantic 才是业务 Schema 边界。

## 练习 9：模型 Evidence 覆盖高是否代表准确

参考思路：

不代表。Coverage 只表示字段有引用来源。模型可能引用了错误行或错误解释。
需要同时看 Field Accuracy、Line F1、Schema Rate 和人工证据检查。

## 练习 10：Candidate Score 为什么不是概率

定位：`candidate_matching_service.assess_candidate`

参考思路：

它是人工配置权重的加总并裁剪到 0–100，没有训练、校准或概率分布。它只能被
称为解释性规则分。

## 练习 11：如何把项目升级到生产

回答应按风险排序，而不是堆技术名：

1. 真实脱敏数据和多模型全量评测；
2. 四眼审批、权限和租户隔离；
3. 多 Worker fencing、幂等和事务 outbox；
4. 文件扫描、TLS、KMS、保留策略；
5. 指标、Tracing、告警和容量测试；
6. 备份、恢复和灾备演练。

## 练习 12：如何证明你真的理解项目

现场选择一条具体链路：

```text
上传 -> Run -> MinerU -> LLM -> Draft -> Version -> Reconciliation
```

对每一步回答：

- 输入输出是什么；
- 状态保存在哪里；
- 失败如何表现；
- 哪一步能重试；
- 哪一步需要人工；
- 哪一步使用模型；
- 哪一步保证确定性。
