# ADR 0001：分离 Parser 与 Normalizer

- 状态：Accepted
- 日期：2026-07-31

## 背景

财务 PDF 同时包含 OCR/版面问题和业务字段映射问题。如果一个端到端调用失败，
难以判断错误来自文字识别还是语义归一化。

## 决策

MinerU 负责 Parser；OpenAI-compatible 文本模型负责 Normalizer。二者通过
`ParseResult` Contract 解耦，MinerU 结果按原件哈希缓存。

## 结果

优点：

- Prompt/模型实验不重复解析；
- 错误可分层定位；
- Evidence 可引用解析文本；
- Parser/Normalizer 可独立替换。

代价：

- 增加一次服务调用和中间数据；
- 解析错误会传递到归一化；
- 需要分别监控成本和延迟。

## 重新评估条件

视觉模型在同一 Gold 数据集上证明准确率、证据、延迟或总成本明显更优时，
可以新增 ADR 改为端到端或混合路线。
