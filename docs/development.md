# 开发与运行

## 初始化

项目根目录：`E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation`。

```powershell
Copy-Item .env.example .env
uv sync
.\.venv\Scripts\python.exe init_database.py
```

开发工作台需要以下 `.env` 配置：

```dotenv
APP_ENV=dev
WORKSPACE_ENABLED=true
WORKSPACE_TENANT_ID=demo-tenant
WORKSPACE_STORE_ID=demo-store
WORKSPACE_POLL_SECONDS=3
```

## 管理员和启动

在 IDE 中直接运行 `setup_dev_admin.py` 可创建或重置 `adminuser`。脚本仅在非生产环境
运行，每次生成临时强密码并撤销旧 Session。正式账号仍使用交互命令：

```powershell
.\.venv\Scripts\python.exe -m app.cli.create_admin --username reviewer --role reviewer
```

在 IDE 中运行 `run_local_demo.py`，或执行 `start_local_demo.ps1`。启动器复用已存在的
本项目进程，启动 API、Extraction Worker、Workspace Worker 和前端，写日志到
`logs/local-demo/`，健康检查后打开 <http://127.0.0.1:5274>。

停止运行：`stop_local_demo.ps1`。API 文档：<http://127.0.0.1:8200/docs>。
Extraction Quality Lab：<http://127.0.0.1:5274/lab>。

工作台的正常路径只显示自动关联摘要和一次确认入口；候选选择仅在无法唯一关联或用户点击
“修改关联”时展开。结构化表单对 Reviewer 开放，高级 JSON 编辑仅对 Admin 开放。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
uv run ruff check .
```

需要 PostgreSQL 的测试必须使用显式隔离的 `IVIDA_TEST_POSTGRES_URL`；测试套件拒绝连接
开发库或生产库。测试启动时固定关闭本机工作台开关，需要启用场景的测试自行覆盖配置，
因此开发 `.env` 不会改变单元测试结果。缺少外部 MinerU、模型或 MinIO 时，只跳过对应
集成验证，不伪报通过。

## CI/CD

GitHub Actions 执行后端测试、前端测试与构建、Ruff、文档同步、Compose smoke 和镜像扫描。
版本 Tag 通过后生成版本化 GHCR 镜像和预发布记录，保存镜像 Digest、Git commit 与
Alembic revision。GitHub-hosted Runner 使用 PostgreSQL Service Container 和
`IVIDA_TEST_POSTGRES_URL`；流程不连接现有服务器，不自动部署，也不自动 downgrade。

## 快速排障

| 现象 | 检查 |
|---|---|
| 登录失败 | 运行 `setup_dev_admin.py`，确认 API 使用同一 `.env` |
| 上传后一直等待 | 两个 Worker 是否运行，`/api/runtime/status` 是否在线 |
| 新工作台未出现 | 数据库是否迁移到 head，`WORKSPACE_*` 是否有效，重启 API |
| 文件无法查看 | MinIO、对象是否存在，以及当前 workspace 授权 |
| 409 | 页面数据过期；刷新后重新确认，不静默覆盖输入 |
| 模型失败 | MinerU/Normalizer 配置、超时和 phase error code |

业务错误码以 API 响应和领域枚举为准，不在文档复制长表。

## 文档规则

只维护本目录五个主题文档和入口页。代码变化同步更新最相关的一份文档，并运行：

```powershell
.\.venv\Scripts\python.exe tools\check_documentation_sync.py --base-ref <base>
```

不要新增按日期堆积的设计稿、实施计划或重复 API/数据库手册。需要冻结的新业务契约写入
`spec/`，讨论和旧方案留在 Git 历史。
