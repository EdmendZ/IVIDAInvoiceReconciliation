# AI 抽取与评测

## 处理链路

1. API 校验文件类型、大小和真实文件头，将原件保存到 MinIO。
2. Extraction Worker 领取数据库任务并提交 MinerU。
3. MinerU 返回 Markdown、表格和页级内容；原始产物单独保存。
4. OpenAI-compatible 文本模型只把解析内容转换为固定 JSON Schema。
5. Pydantic 和确定性规则检查必填字段、金额、GST、行项目和证据覆盖。
6. 工作台生成可修订版本；最终匹配与差异计算不由模型决定。

模型或 MinerU 未配置时任务以稳定错误结束，不生成虚假财务结果。每次运行记录
provider、model、prompt version、token、耗时和估算成本，但不暴露 API key 或地址。

## 证据和未知值

字段证据保存页码、原文片段和定位信息。人工修改保留来源关系并记录原因。没有读取到
的 quantity、unit price、tax 或 total 保持未知；系统只允许用户明确确认实际看过的
未核验维度。

## 评测

本地合成集覆盖英文澳洲门店单据、表格、GST、分批收货、缺失价格和版式变化。
核心指标包括 Schema 通过率、字段准确率、行项目 F1、证据覆盖率、延迟和成本。

评测运行和 dataset identity 不可变；失败必须进入分母。Admin 可以在 `/lab` 比较
baseline 和 candidate，但 Promotion Decision 不会自动修改生产模型配置。只有明确
确认的 `model_error` Feedback Candidate 才能进入 Gold，其余分类保留审计记录。
结果为 `inconclusive` 时不能宣称模型提升。

```powershell
.\.venv\Scripts\python.exe -m app.cli.evaluate_extraction --variant baseline
.\.venv\Scripts\python.exe -m app.cli.create_experiment --help
.\.venv\Scripts\python.exe -m app.cli.run_experiment --help
```

真实模型结论必须来自同一数据集和同一解析缓存的可重复比较；一次冒烟调用不能作为
准确率证明。
