# IVIDA Invoice Reconciliation

IVIDA 发票（Invoice）与收货单（Receive Note）比对原型。该项目与客服知识库项目完全分离，只复用同一套基础设施服务。

第一次阅读项目请从 [文档中心](docs/README.md) 开始。业务、架构、AI 抽取、
人工审核、一对多核对、运行排障和面试复习均有独立说明。修改代码时必须遵守
[文档维护规范](docs/documentation-policy.md)，并同步更新对应文档。

## 当前阶段

阶段 1 已建立：

- 独立 FastAPI 服务，默认端口 `8200`
- Invoice / Receive Note 标准 JSON 数据模型
- Taptouch Receiving 结构化、幂等、带版本导入（绕过 OCR 和虚假人工审核）
- 支持“一张发票对应多张收货单”的确定性行项目比对
- 数量、单价、金额容差与差异分类
- PDF、PNG、JPEG 原件上传与安全格式校验
- MinIO 原件存储与 PostgreSQL 抽取任务持久化
- 异步抽取运行记录和 `ready_for_review` 状态流
- 模型 Provider 统一接口、耗时、Token 和成本字段
- 异常 Reconciliation 与差异 Case 的同事务创建，清洁结果不制造人工待办
- Reviewer 认领、逐项处置和提交，Admin 退回、重新分派、批准或作废
- `expected_revision` 乐观并发保护与追加式 Case Action 审计历史
- PostgreSQL、MinIO 和模型供应商的独立配置命名
- 健康检查、示例接口和自动化测试

当前已接通 MinerU 文档解析和 OpenAI-compatible 结构化模型，并保留
`MODEL_PROVIDER=disabled` 作为未配置环境的安全默认值。模型只生成审核草稿；
最终比对只接受人工批准的上传版本，或当前有效的 Taptouch 上游权威版本。

## 启动

### 推荐：一键启动本机演示

```powershell
cd E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation
.\start_local_demo.ps1
```

脚本会启动 API、Extraction Worker 和前端，验证 `8200`、`5274`
端口及健康检查，然后打开 <http://127.0.0.1:5274>。日志保存在
`logs/local-demo/`。

停止时运行：

```powershell
.\stop_local_demo.ps1
```

停止脚本只处理启动器记录且可验证属于本项目的进程，不会按端口盲目结束其他应用。

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

项目本地包含一套澳洲披萨门店采购合成评测集，位于 `evaluation_data/`，并已被 Git 忽略。生成器、场景说明和校验方式见 [docs/evaluation-dataset.md](docs/evaluation-dataset.md)。

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
[API、UI 与本地运行](docs/operations/08-api-ui-and-local-run.md)。

模型选择不是写死的：先用同一份 MinerU 缓存分别评测 Max、Plus 或 Flash，
再按 Schema 通过率、字段准确率、行项目 F1、证据覆盖率、延迟和成本选择。
当前单文档结果只是链路冒烟测试，不作为生产模型结论。具体依据见
[docs/interview/model-selection.md](docs/interview/model-selection.md)。

## 人工审核与对账

- 审核前端：<http://127.0.0.1:5274>
- `Upload`：上传 Invoice/Receive Note、启动处理并查看 Worker 阶段。
- `Review`：查看证据与校验问题、保存新版本、批准或驳回。
- `Reconcile`：选择已批准 Invoice 和一个或多个 Receive Note，展示逐行差异。
- `Cases`：查看公共待办和本人 Case；负责人逐项填写结论，Admin 处理审批或作废决定。
- 账号创建：`python -m app.cli.create_admin --username reviewer --role reviewer`
- 只有人工批准的上传版本或当前有效的 Taptouch 权威版本可以调用生产对账接口。
- 编辑会创建新版本；批准版本与审核记录由 PostgreSQL 触发器保护。

Reconciliation 是不可覆盖的规则计算快照；Case 只保存可变的人工处理状态和审计
轨迹。`approved`、`voided` Case 不能恢复或继续编辑，需要纠正单据时应基于新的批准
版本创建新的 Reconciliation。本仓库当前仍是本机 Pilot，不包含 Case 补充材料附件
上传、通知、SLA/分析报表或生产部署能力。

完整启动顺序、恢复和备份说明见
[docs/operations/review-workflow.md](docs/operations/review-workflow.md)。

## CI/CD 与容器演示

[![CI](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/ci.yml/badge.svg)](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/ci.yml)
[![CodeQL](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/codeql.yml/badge.svg)](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/codeql.yml)

复制 `.env.compose.example` 为 `.env.compose` 后，可运行
`docker compose --env-file .env.compose up --build -d` 启动完整本地演示栈。
`v*` Tag 会在完整 CI、Compose Smoke 和镜像扫描通过后发布三个 GHCR 镜像及
GitHub Release。该流程用于模拟企业交付，不代表已经部署到生产服务器。命令、
回滚边界和仓库设置见
[CI/CD、容器发布与回滚](docs/operations/20-ci-cd-and-release.md)。

## 不连接外部服务学习业务规则

在 PyCharm 中直接右键运行根目录的 `demo_business_flow.py`，可以观察一张
Invoice 与两张分批 Receive Notes 的候选匹配和一对多核对。该脚本不读取
`.env`，不连接 PostgreSQL、MinIO、MinerU 或模型 API。

断点位置和变量观察顺序见
[PyCharm 断点调试业务流程](docs/tutorial/19-pycharm-debug-walkthrough.md)。

## 面试材料

- [项目故事](docs/interview/project-story.md)
- [五分钟演示脚本](docs/interview/demo-script.md)
- [架构与责任边界](docs/interview/architecture.md)
- [模型选择记录](docs/interview/model-selection.md)
