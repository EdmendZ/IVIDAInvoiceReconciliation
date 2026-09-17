# IVIDA Invoice Reconciliation

IVIDA 发票（Invoice）与收货单（Receive Note）比对原型。该项目与客服知识库项目完全分离，只复用同一套基础设施服务。

第一次阅读项目请从 [文档中心](docs/README.md) 开始。业务、架构、AI 抽取、
人工审核、一对多核对、运行排障和面试复习均有独立说明。修改代码时必须遵守
[开发与文档规范](docs/development.md)，并同步更新对应文档。

## 当前阶段

当前本地 Pilot 已建立：

- 独立 FastAPI 服务，默认端口 `8200`
- Invoice / Receive Note 标准 JSON 数据模型
- Taptouch Receiving 结构化、幂等、带版本导入（绕过 OCR 和虚假人工审核）
- 支持“一张发票对应多张收货单”的确定性行项目比对
- 数量、单价、金额容差与差异分类
- PDF、PNG、JPEG 原件上传与安全格式校验
- MinIO 原件存储与 PostgreSQL 抽取任务持久化
- 异步抽取运行记录和后台自动处理
- 模型 Provider 统一接口、耗时、Token 和成本字段
- Invoice 与 Receive Note 任意顺序到达，系统自动关联并生成逐行预览
- 正常结果和差异结果都只需一次人工确认，不使用认领、分派或多级审批
- 自动关联默认折叠；只有关联不明确或用户主动修改时显示候选选择
- 不可变确认快照、`expected_revision` 乐观并发保护和追加式操作审计
- PostgreSQL、MinIO 和模型供应商的独立配置命名
- 健康检查、示例接口和自动化测试

当前已接通 MinerU 文档解析和 OpenAI-compatible 结构化模型，并保留
`MODEL_PROVIDER=disabled` 作为未配置环境的安全默认值。模型只生成审核草稿；
最终差异由确定性规则计算，并由用户在工作台确认一次。TapTouch Receiving 已有受保护
的适配接口，但尚未接入真实生产 API。

## 启动

### 推荐：一键启动本机演示

在 PyCharm 或其他 IDE 中直接运行根目录的 `run_local_demo.py`。它复用下方已经验收的
PowerShell 启动器，不维护第二套启动流程。

也可以在 PowerShell 中运行：

```powershell
cd E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation
.\start_local_demo.ps1
```

脚本会启动 API、Extraction Worker、Workspace Worker 和前端，验证 `8200`、`5274`
端口及健康检查，然后打开 <http://127.0.0.1:5274>。日志保存在
`logs/local-demo/`。

停止时运行：

```powershell
.\stop_local_demo.ps1
```

停止脚本只处理启动器记录且可验证属于本项目的进程，不会按端口盲目结束其他应用。

开发阶段需要快速创建或重置管理员时，直接运行根目录的 `setup_dev_admin.py`。脚本
默认处理 `adminuser`，每次生成新的临时强密码、恢复 Admin 权限并注销旧 Session；
生产环境会拒绝运行。

创建管理员并配置工作台范围后，可运行根目录的 `setup_demo_data.py`。该脚本在非生产
环境幂等创建六份英文 PDF，展示 Invoice/Receive Note 分别等待、自动一致和数量差异
四类工作台状态。它复用正式上传用例、PostgreSQL Repository 和 Workspace Worker，
但会为这些固定文件写入明确标记的 demo fixture Draft，绕过 MinerU 和结构化模型。
这些数据只用于体验已验收的工作台流程，不代表真实抽取准确率，也不代表已接入真实
TapTouch。脚本只输出场景 document ID 和显示状态，不输出密码、Token 或连接配置。

### 分别启动组件

```powershell
cd E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation
Copy-Item .env.example .env
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8200 --reload
```

在 PyCharm 中也可以直接右键根目录下的 `run_api.py`，选择 **Run 'run_api'**。

首次运行前，在 PyCharm 中右键 `init_database.py`，选择 **Run 'init_database'**。脚本会在 PostgreSQL 中创建独立数据库（如果尚不存在），然后执行 Alembic 表结构迁移。

打开：

- API 文档：<http://localhost:8200/docs>
- 健康检查：<http://localhost:8200/api/health>
- 输入示例：<http://localhost:8200/api/reconciliations/example>

## 上传测试

打开 <http://localhost:8200/docs>：

1. 展开 `POST /api/documents/upload`。
2. 点击 **Try it out**。
3. `document_type` 选择 `invoice` 或 `receive_note`。
4. 选择 PDF、PNG、JPG 或 JPEG 文件。
5. 点击 **Execute**。
6. 成功时返回 `task_id`、MinIO 对象路径以及 `uploaded` 状态。
7. 将 `task_id` 填入 `GET /api/extraction-tasks/{task_id}` 可再次查询。

抽取框架接口：

- `POST /api/extraction-tasks/{task_id}/extract`：创建 PostgreSQL 持久化抽取任务。
- `GET /api/extraction-runs/{run_id}`：查询执行阶段、耗时和成本。
- `GET /api/extraction-runs/{run_id}/result`：查询草稿、证据和校验问题。

API 不再使用进程内 `BackgroundTasks`。必须单独运行
`run_extraction_worker.py`；API 或 Worker 重启不会丢失排队任务。在真实模型
尚未配置时，Worker 会以稳定错误码结束任务，不会产生虚假的财务结果。

真实上传前，需要复制 `.env.example` 为 `.env`，填写 PostgreSQL 连接和当前 MinIO 的有效账号。可以复用项目2的 MinIO 服务器参数，但必须保留：

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@YOUR_HOST:5432/ivida_invoice_reconciliation
MINIO_BUCKET_NAME=ivida-invoice-documents
TAPTOUCH_INTEGRATION_TOKEN=YOUR_RANDOM_LOCAL_TOKEN
```

多门店集成应使用 `TAPTOUCH_INTEGRATION_CREDENTIALS_JSON` 为每个调用方限制允许的
tenant/store；单 Token 只适合本地演示。

这样两个项目可以共用 MinIO 服务进程，但不会共用业务数据。

运行测试：

```powershell
uv run pytest
```

## 基础设施隔离

| 资源 | 当前项目 |
|---|---|
| 后端端口 | `8200` |
| 预留前端端口 | `5274` |
| PostgreSQL database | `ivida_invoice_reconciliation` |
| MinIO bucket | `ivida-invoice-documents` |
| Milvus | 阶段 1 不使用 |

PostgreSQL 和 MinIO 可以使用现有服务器；database 与 bucket 必须使用上表中的独立名称。当前项目不再依赖 MongoDB。

## 评测数据

项目本地包含一套澳洲披萨门店采购合成评测集，位于 `evaluation_data/`，并已被 Git 忽略。生成器、场景说明和校验方式见 [docs/ai.md](docs/ai.md)。

评测命令会缓存 MinerU 解析结果，再计算结构化字段准确率、行项目 F1、
证据覆盖率、延迟和估算成本：

```powershell
.\.venv\Scripts\python.exe -m app.cli.evaluate_extraction `
  --variant baseline `
  --max-documents 1
```

使用 `app.cli.compare_evaluations` 可以比较不同 Prompt 或模型的
`summary.json`，而不重复调用 MinerU。

Admin 可在 <http://127.0.0.1:5274/lab> 使用 Extraction Quality Lab 查看不可变实验
定义、完整运行指标、错误切片、Promotion Gate 和待确认 Feedback Candidate。真实模型
实验只由 `app.cli.create_experiment` / `app.cli.run_experiment` 执行；Web API 不调用
外部模型。推荐结论不会自动切换生产配置，只有 Admin 确认的 `model_error` 才有 Gold
资格。详细命令与 5–8 分钟演示顺序见
[开发与运行](docs/development.md)。

模型选择不是写死的：先用同一份 MinerU 缓存分别评测 Max、Plus 或 Flash，
再按 Schema 通过率、字段准确率、行项目 F1、证据覆盖率、延迟和成本选择。
当前单文档结果只是链路冒烟测试，不作为生产模型结论。具体依据见
[docs/ai.md](docs/ai.md)。

## 简化工作台

- 工作台：<http://127.0.0.1:5274>
- 上传 Invoice 或 Receive Note 后，两个 Worker 在后台自动处理，无需点击开始提取或匹配。
- 另一方尚未到达时保留为“等待另一方单据”；到齐后自动关联并生成逐行结果。
- 用户在同一详情页核对原件、英文业务字段、关联单据和差异，然后确认一次。
- 有差异时可以先标记待核实，或填写处理说明后确认；不创建认领和二次审批流程。
- 确认保存不可变快照；后续更正必须重开，历史结果不会被覆盖。
- 账号创建：`python -m app.cli.create_admin --username reviewer --role reviewer`

本仓库仍是本机 Pilot，不包含真实 TapTouch 生产接入、通知、SLA、付款、总账或生产部署。

完整启动顺序、恢复和备份说明见
[开发与运行](docs/development.md)。

## CI/CD 与容器演示

[![CI](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/ci.yml/badge.svg)](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/ci.yml)
[![CodeQL](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/codeql.yml/badge.svg)](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/codeql.yml)

复制 `.env.compose.example` 为 `.env.compose` 后，可运行
`docker compose --env-file .env.compose up --build -d` 启动完整本地演示栈。
`v*` Tag 会在完整 CI、Compose Smoke 和镜像扫描通过后发布三个 GHCR 镜像及
GitHub Release。该流程用于模拟企业交付，不代表已经部署到生产服务器。命令、
回滚边界和仓库设置见
[开发与运行](docs/development.md)。

## 不连接外部服务学习业务规则

在 PyCharm 中直接右键运行根目录的 `demo_business_flow.py`，可以观察一张
Invoice 与两张分批 Receive Notes 的候选匹配和一对多核对。该脚本不读取
`.env`，不连接 PostgreSQL、MinIO、MinerU 或模型 API。

断点位置和变量观察顺序见
[演示与源码导读](docs/demo.md)。

## 演示与讲解

- [五分钟演示与源码导读](docs/demo.md)
- [架构与责任边界](docs/architecture.md)
- [模型选择与评测边界](docs/ai.md)
