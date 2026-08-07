# 人工审核与版本治理

## 为什么模型输出不能直接进入核对

单据抽取具有三个不可避免的不确定性：

- OCR 可能把水印、页眉或 ABN 当作供应商名称；
- 表格列可能错位；
- LLM 可能遗漏行号、单位或采购订单号。

因此 `ready_for_review` 的意思是“可供人检查”，不是“业务正确”。

## 审核页面在做什么

审核详情页同时展示：

- 结构化字段编辑器；
- 字段对应的原文 Evidence；
- Schema 和财务 Validation Issues；
- 单据类型确认；
- 模型、Prompt、Token、延迟和成本；
- 保存、驳回和批准操作。

## 首次进入审核

`ReviewService.start_review(task_id, user)`：

1. 如果该 Task 已有 Version，返回最新 Version；
2. 否则读取机器 Draft；
3. 创建 Version 1；
4. 写入 `review_started` 审核动作。

这个操作是幂等的：重复进入不会无限创建 Version。

## 为什么保存编辑会创建新版本

假设模型将供应商名称识别为水印，审核人员修改后：

```text
Version 1：supplier.name = "SYNTHETIC DOCUMENT"
Version 2：supplier.name = "Southern Cross Foodservice Pty Ltd"
```

如果直接覆盖 Version 1，就无法回答：

- 模型最初输出了什么；
- 谁修改了字段；
- 修改原因是什么；
- 哪个版本后来被批准。

`ReviewService.save_edit()` 因此验证新 JSON 后创建下一版本，并记录
`document_edited` 动作及 old/new value。

## 单据类型为什么必须确认

Invoice 和 Receive Note 可能布局相似。如果一张发票被误分类为收货单，后续
候选逻辑可能把它与自己匹配。因此系统要求：

- 审核人员勾选确认当前类型；
- 类型错误时执行 Reclassify；
- Reclassify 创建新版本和审计动作；
- Approve 请求中的确认类型必须与 Version 类型一致。

## Blocking 与 Warning

| 类型 | 示例 | 是否阻止批准 |
|---|---|---|
| Blocking | 行金额不等于数量乘单价 | 是 |
| Blocking | 总额不等于小计加税额 | 是 |
| Warning | 缺少采购订单号 | 否，但需人工关注 |

批准时服务会重新执行校验，不能只信任前端几秒前的预览。

## 批准门禁

批准必须同时满足：

1. 当前 Version 是该 Task 的最新版本；
2. 当前 Version 状态为 draft；
3. 审核人员确认的类型一致；
4. JSON 能通过对应 Schema；
5. 没有 Blocking Issue。

批准后：

- 写入 approved_by 和 approved_at；
- 追加 approved 审核动作；
- Version 变为不可编辑；
- 才能被 ReconciliationApplicationService 读取。

## 驳回

驳回必须填写原因。驳回说明当前版本不应继续使用，但不会删除原件、机器 Draft
或审核历史。

## 前后端双重校验

前端提供 Live Validation 是为了即时反馈；后端批准时再次校验是安全边界。

不能只依赖前端，因为 HTTP 请求可以绕过 UI，浏览器状态也可能过期。

## 审核修改如何形成模型反馈

`FeedbackService` 从不可变 Version、追加式 `ReviewAction`、精确来源 Draft 和原始
Extraction Run 组合出可追溯候选，记录模型/Prompt、字段路径及 old/new value。
字典递归比较；商品行先按唯一 SKU、再按规范化描述匹配，避免排序变化制造伪差异；
没有稳定身份或存在重复身份时退回整个 `items` 列表差异，不冒充精确字段反馈。

候选不会自动成为 Gold。只有 Admin 可以确认分类，并且只有 `model_error` 能将
`include_in_gold` 设为 true；可接受变体、人工纠错错误和业务上下文新增都保留审计，
但不能作为模型应从原件推断出的标准答案。重复收集保持幂等；已确认判断发生变化时
创建带 `supersedes_candidate_id` 的新候选，不覆盖原确认记录。

## 常见追问

### 为什么不是“四眼审批”

Pilot 当前只有 reviewer/admin 角色和单人批准。生产财务系统通常需要提交者与
批准者分离，甚至金额分级审批。它已列入生产演进，不应在面试中声称完成。

### 编辑后原 Evidence 是否仍然可信

Evidence 描述的是机器抽取时的原文来源。人工编辑后应结合原件再次核对。
当前 Version 保存修改动作，但尚未为每次人工修改生成独立 Evidence，这是一项
可明确说明的改进方向。Feedback Candidate 保存的是治理和训练评测线索，不等于
原件 Evidence。

### 为什么批准版本必须不可变

核对结果引用 Version ID。如果批准版本可以被覆盖，历史核对结果会在没有新
记录的情况下改变含义，破坏审计一致性。

## 面试复习点

- Human-in-the-loop 不是 UI 按钮，而是一组服务端门禁；
- Versioning 防止静默覆盖；
- Live Validation 改善体验，Server Validation 才是信任边界；
- Reclassification 解决同号 Invoice/Receive Note 的严重误分类风险；
- Approved Version 是核对服务唯一可信输入。
- Reviewer 修改只是反馈候选；Admin 分类确认后，只有模型错误才有 Gold 资格。
