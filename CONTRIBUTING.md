# Contributing

本项目把文档视为业务契约的一部分。

提交代码前：

1. 阅读 [文档中心](docs/README.md)；
2. 根据 [代码—文档映射](docs/code-document-map.json) 更新对应说明；
3. 遵守 [文档维护规范](docs/documentation-policy.md)；
4. 运行：

```powershell
.\.venv\Scripts\python.exe tools\check_documentation_sync.py
.\.venv\Scripts\python.exe -m pytest
Set-Location frontend
npm test -- --run
npm run build
```

任何改变业务规则、状态、API、Schema、Prompt、存储结构或用户操作的提交，
必须同时包含文档更新。纯格式化或等价重构只能在人工确认行为未变化后使用
`--allow-code-only`。
