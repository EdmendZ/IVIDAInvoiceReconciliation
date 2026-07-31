# 五分钟面试演示脚本

## 0:00–0:40 问题与边界

说明一张 Invoice 可能对应多张分批 Receive Note。项目目标是减少人工找差异
的时间，不是让大模型自动批准付款。演示数据全部为合成澳洲披萨采购单据。

## 0:40–1:10 一键启动

```powershell
cd E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation
.\start_local_demo.ps1
```

打开 <http://127.0.0.1:5274>。指出 API、独立 Worker、PostgreSQL、MinIO 和
React 前端是分离组件；Worker 心跳让 `queued` 与“Worker 未启动”可区分。

## 1:10–2:00 上传与异步抽取

上传同一业务场景的一张 Invoice 和两张 Receive Note。展示任务经历：

`queued → parsing → normalizing → ready_for_review`

解释 MinerU 处理版面和表格，LLM 归一化字段；取消是协作式取消，远端任务
已经提交时可能继续运行，但本地不会再生成审核草稿。

## 2:00–3:05 证据化审核

进入 Review：

- 展开 `Model run`，查看模型、Prompt 指纹、Token 和延迟；
- 点选结构化字段，核对原文证据；
- 展示 Schema/金额校验；
- 修正一处错误会创建新版本，不覆盖旧版本；
- 确认单据类型后批准。

强调模型输出只是 Draft，批准版本不可变。

## 3:05–4:00 一对多对账

在 Reconcile 选择一张已批准 Invoice 和两张已批准 Receive Note。说明系统按
采购订单和商品行汇总数量、单价和金额，规则引擎输出差异类型与候选依据，
不是让 LLM 直接给出“可付款”结论。

## 4:00–4:40 评测

展示 `docs/interview/model-selection.md`：

- MinerU 缓存使模型对比不重复 OCR；
- 单文档冒烟结果为字段准确率 89.47%、行项目 F1 100%、证据覆盖率 89.47%；
- 指出供应商名称受合成水印干扰、行号遗漏；
- 解释评测器曾错误处理 `document.` 前缀，修复后可离线复算。

这是“验证评测器再评价模型”的具体案例。

## 4:40–5:00 取舍与下一步

当前没有声称选出最佳模型。下一步跑满 17 份材料，对比 Max、Plus、Flash 的
准确率、Schema 失败率、P95 延迟与成本，然后才决定默认模型。企业化工作
包括四眼审批、对象存储安全、Worker 多实例和监控灾备。
