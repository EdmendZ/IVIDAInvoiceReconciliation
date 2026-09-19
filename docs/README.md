# IVIDA 发票核对项目文档

先阅读仓库根目录 [README](../README.md) 了解界面、主流程、架构和启动方式。本目录只保留
六个长期主题入口，避免代码、Spec 和多份说明互相冲突。

| 文档 | 内容 |
|---|---|
| [产品与流程](product.md) | 业务范围、用户流程、匹配与确认规则、后续边界 |
| [架构](architecture.md) | 分层、模块交互、数据和安全边界 |
| [AI 抽取与评测](ai.md) | MinerU、结构化模型、证据、确定性校验和评测 |
| [开发与运行](development.md) | 初始化、账号、启动、测试、CI/CD 和排障 |
| [演示与源码导读](demo.md) | 五分钟演示、项目讲解和阅读顺序 |
| [冻结 Spec](../spec/README.md) | 当前简化工作台的接口、状态机、规则和任务权限 |

权威顺序：冻结 Spec → 代码与数据库迁移 → 本目录说明。API 细节查看运行时
`/docs`，表结构查看 `app/infra/database_models.py` 和 `migrations/`，不再复制一份
容易过期的全量清单。

README 中的工作台截图来自当前 React 前端和确定性 demo fixture；图片只说明界面与状态，
不代表真实 OCR、模型、生产数据或 TapTouch 已经联通。文档图片统一放在 `docs/assets/`。
