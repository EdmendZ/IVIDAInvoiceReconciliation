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
- Gold JSON 能通过当前 Pydantic 数据模型。
- 每个场景得到预期的比对分类和人工审核状态。

真实客户文件只能在完成脱敏和内部批准后加入，并且仍应保留在 Git 忽略目录内。

