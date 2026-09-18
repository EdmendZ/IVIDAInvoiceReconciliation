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

需要固定工作台演示状态时，先创建 `adminuser`，确认 PostgreSQL、MinIO 及
`WORKSPACE_ENABLED=true` 已配置，再在 IDE 中运行 `setup_demo_data.py`，或执行：

```powershell
.\.venv\Scripts\python.exe setup_demo_data.py
```

脚本从服务端 `WORKSPACE_TENANT_ID` / `WORKSPACE_STORE_ID` 读取范围，不接受命令行门店
参数。它幂等上传六份有效英文 PDF，并通过既有 WorkspaceService、PostgreSQL Repository
和 Workspace Worker 形成四类可见结果：Invoice 等待 Receive Note、Receive Note 等待
Invoice、自动关联且数量一致、自动关联但数量有差异。重复执行复用原 Task、Run、Draft、
工作台单据、Revision 和 Preview。若缺少 `adminuser`，脚本会提示先运行
`setup_dev_admin.py`；production 环境会在访问数据库或对象存储前拒绝执行。

这些固定 Draft 明确标记为 demo fixture，并绕过 MinerU、真实模型和 TapTouch。该入口只
演示工作台业务流程，不能用于宣称抽取准确率或真实 TapTouch 生产接入。标准输出仅包含
每个场景的 document ID、显示状态和预览结果，不包含密码、Token、DSN 或其他 Secret。

要在网页端查看完整评测集，确认 `evaluation_data/` 已存在后运行：

```powershell
.\.venv\Scripts\python.exe setup_evaluation_data.py
```

该入口会导入 8 个案例的 17 份英文 PDF，并用对应 Gold JSON 创建 evaluation fixture
Draft，再由 Workspace Worker 生成网页列表和预览状态。它同样只允许开发环境，重复运行
复用既有记录，不调用 OCR、模型或 TapTouch；数据集缺失或原件与 Gold 不一致时会停止。

在 IDE 中运行 `run_local_demo.py`，或执行 `start_local_demo.ps1`。启动器复用已存在的
本项目进程，启动 API、Extraction Worker、Workspace Worker 和前端，写日志到
`logs/local-demo/`，健康检查后打开 <http://127.0.0.1:5274>。

健康检查显式使用 `Invoke-WebRequest -UseBasicParsing`，以兼容 `run_local_demo.py` 调用的
Windows PowerShell 5.1。不要删除该开关；否则 API 即使已经返回 HTTP 200，也可能因旧 IE
HTML 解析组件不可用而被误报为启动超时，随后启动器会按安全回滚停止本次创建的进程。

停止运行：`stop_local_demo.ps1`。API 文档：<http://127.0.0.1:8200/docs>。
Extraction Quality Lab：<http://127.0.0.1:5274/lab>。

停止脚本只处理启动器记录且仍能验证归属的进程，并连同 Python 启动器的子进程一起
停止；手工启动或其他项目占用端口的进程不会被终止。

工作台的正常路径只显示自动关联摘要和一次确认入口；候选选择仅在无法唯一关联或用户点击
“修改关联”时展开。结构化表单对 Reviewer 开放，高级 JSON 编辑仅对 Admin 开放。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
uv run ruff check .
```

本地已有的合成澳洲采购数据集还可以用于工作台规则验收。它位于被 Git 忽略的
`evaluation_data/`，包含 8 个案例、17 份英文 PDF 和 Gold JSON；Gold JSON 是已提取的
结构化输入，不能用来宣称真实 OCR 或模型准确率：

```powershell
.\.venv\Scripts\python.exe tools\validate_evaluation_dataset.py
.\.venv\Scripts\python.exe -m pytest tests\test_workspace_evaluation_dataset.py -q
```

如果当前 checkout 没有这套本地数据，工作台数据测试会明确跳过；不会生成替代数据或
把跳过当作通过。测试只验证现有匹配、逐行比对、容差和人工选择门槛，不连接 TapTouch。

需要 PostgreSQL 的工作台测试必须使用显式隔离的 `WORKSPACE_TEST_DATABASE_URL`，且数据库名
必须以 `_workspace_test` 结尾；测试套件拒绝连接开发库或生产库。测试启动时固定关闭本机
工作台开关，需要启用场景的测试自行覆盖配置，
因此开发 `.env` 不会改变单元测试结果。缺少外部 MinerU、模型或 MinIO 时，只跳过对应
集成验证，不伪报通过。

旧版说明曾使用 `IVIDA_TEST_POSTGRES_URL`；它只作为历史名称保留，工作台测试不再读取该变量。

## CI/CD

GitHub Actions 执行后端测试、前端测试与构建、Ruff、文档同步、Compose smoke 和镜像扫描。
版本 Tag 通过后生成版本化 GHCR 镜像和预发布记录，保存镜像 Digest、Git commit 与
Alembic revision。GitHub-hosted Runner 使用 PostgreSQL Service Container 和
`WORKSPACE_TEST_DATABASE_URL`；流程不连接现有服务器，不自动部署，也不自动 downgrade。

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
