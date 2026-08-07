# 澳洲餐饮采购评测集

评测数据生成在项目根目录的 `evaluation_data/`。整个目录已加入 `.gitignore`，不会提交到 Git。

## 数据范围

当前版本包含 8 个业务场景、17 份单页 PDF：

1. 单张发票与单张收货单完全一致。
2. 单张发票由两张分批收货单共同满足。
3. 商品短收。
4. 收货记录单价与发票单价不一致。
5. 发票包含未收货商品。
6. 收货单包含未开票商品。
7. 单价和 GST 舍入差异在容差范围内。
8. 发票和收货单的采购订单号不一致。

所有公司、ABN、地址、人员、价格和交易均为虚构。PDF 页首和页尾均明确标记为合成评测材料。

## 目录

```text
evaluation_data/
├─ manifest.json
├─ source_documents/
│  └─ pdf/
├─ gold/
│  └─ 每个单据的人工标准 JSON 和 reconciliation_request.json
├─ cache/
│  └─ 按 PDF SHA-256 保存 MinerU 结果和未完成远端任务
├─ results/
│  └─ 每次评测的逐文档 JSONL、汇总 JSON 和 Markdown 报告
└─ rendered/
   └─ PDF 页面 PNG 与视觉检查总览
```

## 重新生成

在 PyCharm 中运行：

- `tools/generate_evaluation_dataset.py`
- `tools/validate_evaluation_dataset.py`

或在终端运行：

```powershell
uv run python tools\generate_evaluation_dataset.py
uv run python tools\validate_evaluation_dataset.py
```

校验器会检查：

- PDF 文件存在且只有一页。
- PDF 包含合成材料声明和 AUD 字段。
- Document Number、PO、币种、供应商名称、SKU 和非空行号等关键 Gold 值在
  PDF 文本中有明确依据。
- Gold JSON 能通过当前 Pydantic 数据模型。
- 每个场景得到预期的比对分类和人工审核状态。

生成器会在供应商抬头明确打印法定名称，并在 Invoice/Receive Note 商品表中
打印 `Line` 列。这样模型评测不会因为 Gold 要求原件中不存在的行号而奖励推断或
幻觉。PDF 原文支持校验只证明合成文档本身与 Gold 一致；如果 MinerU 没有保留
PDF 中可见的字段，应单独归类为 Parser 错误，而不是通过 Prompt 要求模型猜测。

真实客户文件只能在完成脱敏和内部批准后加入，并且仍应保留在 Git 忽略目录内。

## 抽取评测

第一次运行会调用 MinerU 和结构化模型：

```powershell
.\.venv\Scripts\python.exe -m app.cli.evaluate_extraction `
  --manifest evaluation_data\manifest.json `
  --variant qwen3.7-max-baseline `
  --max-documents 1
```

确认单文档结果后，移除 `--max-documents 1` 即可评测全部 17 份 PDF。

MinerU 结果按原件 SHA-256 缓存。进程中断时，远端 Job ID 会保存为
`*.pending.json`；重新运行将继续轮询该任务，不重复提交。更换 Prompt
或结构化模型时会直接复用 MinerU 缓存。

每次评测输出：

- Schema 通过率
- 字段 micro accuracy
- 行项目 F1
- 字段证据覆盖率
- P50/P95 结构化延迟
- 配置价格后的平均及总 AUD 成本
- 逐字段错误明细

单份文档发生 MinerU、网络、JSON 或 Schema 错误时，评测不会整批中断。
`documents.jsonl` 会记录失败阶段、稳定错误类型和消息，Schema 通过率会将
该文档计为失败，后续文档继续运行。保存的预测 JSON 和证据路径可以用于离线
复算指标，无需再次调用模型。

## 模型对比

分别运行 baseline 和 candidate 后，比较两个 `summary.json`：

```powershell
.\.venv\Scripts\python.exe -m app.cli.compare_evaluations `
  evaluation_data\results\RUN_A\summary.json `
  evaluation_data\results\RUN_B\summary.json `
  --max-cost-aud-per-document 0.10
```

对比器先应用每单成本约束，再按字段准确率、行项目 F1 和证据覆盖率排序。
所有结论只适用于当前合成数据集，不能直接外推客户 ROI。
