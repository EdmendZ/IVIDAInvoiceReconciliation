# API、前端与本机运行

## 一键启动

在 PowerShell 中：

```powershell
Set-Location E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation
.\start_local_demo.ps1
```

访问：

- 前端：<http://127.0.0.1:5274>
- API 文档：<http://127.0.0.1:8200/docs>
- 健康检查：<http://127.0.0.1:8200/api/health>

停止：

```powershell
.\stop_local_demo.ps1
```

启动器会记录自己创建的进程，不会仅凭端口号盲目结束其他程序。

## 三个前端工作区

### Upload

实现：`frontend/src/upload/UploadPage.tsx`

操作流程：

1. 选择 Invoice 或 Receive Note；
2. 可填写采购订单提示；
3. 上传 PDF/PNG/JPEG；
4. 创建 Extraction Run；
5. 观察 Worker 和任务状态；
6. 可对处理中任务请求取消。

状态文案来自 `taskPresentation.ts`，它会结合 Worker online/offline 解释 queued。

### Review

实现：

- `ReviewQueuePage.tsx`；
- `ReviewDocumentPage.tsx`；
- `StructuredDocumentEditor.tsx`。

审核人员查看原文证据、结构化字段和 Validation Issue。`Model run` 面板展示
模型溯源，不展示 API Key 或 Base URL。

### Reconcile

实现：`frontend/src/reconcile/ReconciliationPage.tsx`

只能选择可信不可变版本。先选择 Invoice，再查看解释性 Receive Note 候选；候选
会标出人工上传或 Taptouch Receiving 来源。最后选择一张或多张执行核对。结果
创建成功后可点击 `Export CSV` 下载该次持久化快照；
文件使用 UTF-8 BOM 和标准 CSV 转义，可直接由 Excel 打开。

### Cases

实现：

- `frontend/src/cases/CaseQueuePage.tsx`；
- `frontend/src/cases/CaseDetailPage.tsx`。

`Cases` 导航提供四个队列：公共待认领、我的工作、管理员待决策和已完成记录。
可按 Invoice Number 精确值或前缀筛选，并按最早创建优先稳定分页。Reviewer 在
`Unassigned` 中认领 Case；若其他人已经认领或页面 revision 已过期，界面会显示
冲突并刷新队列。详情页展示不可变核对结果、异常项和完整 Action 历史；只有
后端权限、负责人和状态门禁都允许时，工作流处理控件才可用。

## API 分组

| 路径前缀 | 职责 |
|---|---|
| `/api/auth` | 登录、登出和当前管理员 |
| `/api/documents` | 上传原件 |
| `/api/extraction-*` | 创建、查询、取消抽取 |
| `/api/review` | 草稿审核、版本编辑、批准/驳回 |
| `/api/reconciliations` | 候选、批准版本核对和历史结果 |
| `/api/reconciliation-cases` | 差异 Case 队列、详情、认领和处理工作流 |
| `/api/runtime` | API、数据库、MinIO、Worker 状态 |
| `/api/integrations/taptouch` | Bearer Token 保护的结构化 Receiving 导入 |

浏览器业务路由要求 reviewer/admin 身份。Taptouch 集成使用独立 Bearer Token。
开发环境才注册原始 JSON 对比等诊断接口。

## 认证

管理员密码使用 Argon2 Hash 存储，浏览器通过 Session Cookie 访问业务接口。
前端收到 401 时回到登录页。

创建账号：

```powershell
.\.venv\Scripts\python.exe -m app.cli.create_admin `
  --username reviewer `
  --role reviewer
```

命令会安全读取密码，不应把明文密码提交到 `.env`、SQL 文件或文档。

## 环境变量分组

`.env.example` 按职责分为：

- APP/CORS/上传限制；
- Taptouch 集成 Token；
- PostgreSQL；
- MinIO；
- MinerU；
- Normalization 模型；
- Worker 心跳。

`MINIO_ACCESS_KEY` 类似账号标识，`MINIO_SECRET_KEY` 类似密码。
`MINIO_SECURE=true` 表示通过 HTTPS/TLS 连接 MinIO；本机 HTTP 环境通常为
false，公网生产环境应使用 TLS。

`TAPTOUCH_INTEGRATION_TOKEN` 是机器接口凭据。本地可使用随机值；未配置时接口
保持禁用并返回 401。真实值只能放入被忽略的 `.env` 或部署 Secret，不能提交到
`.env.example`。

## 分别启动

API：

```powershell
.\.venv\Scripts\python.exe run_api.py
```

Worker：

```powershell
.\.venv\Scripts\python.exe run_extraction_worker.py
```

前端：

```powershell
Set-Location frontend
npm run dev
```

必须同时有 API 和 Worker。只有 API 时上传可以成功，但 Run 会一直 queued。

## 运行持久化抽取实验

先确保数据库迁移到 head、`.env` 中 MinerU/Normalization 配置可用，并至少存在
一个 active Admin。创建不可变 baseline 定义：

```powershell
uv run python -m app.cli.create_experiment `
  --name qwen-baseline `
  --role baseline `
  --manifest evaluation_data/manifest.json `
  --required-schema-valid-rate 1 `
  --minimum-field-accuracy 0.95 `
  --minimum-line-item-f1 0.95 `
  --minimum-evidence-coverage 0.90
```

命令标准输出只返回 definition ID。随后执行：

```powershell
uv run python -m app.cli.run_experiment `
  --definition-id <definition-id> `
  --output-root evaluation_data/results
```

执行前会重算 Manifest 和全部原件 Hash，并核对当前 Provider、Model 与 Prompt；
不一致时在调用模型前失败。逐文档失败仍保存在结果与指标分母中，Ctrl+C 会将运行
标记为 cancelled。终端只输出 run ID 和聚合指标，详细预测与报告写入指定目录。

### 5–8 分钟 Quality Lab 演示顺序

真实 API 前提：PostgreSQL 已迁移、MinerU 与 Normalization 凭据有效，并已保存一组
跑满 17 份合成文档的 baseline/candidate 证据。现场只跑一个 candidate 文档，避免
网络等待占满演示：

1. 用 Admin 登录 `/lab`，展示已完成 baseline 及其 dataset identity；
2. 用 `app.cli.run_experiment --definition-id ... --max-documents 1` 实跑一个 candidate 文档；
3. 返回 `/lab` 展示 Parser、Normalizer、Prompt 与数据集来源；
4. 选择已保存的完整 baseline/candidate Run，比较所有 hard gate 与质量 gate；
5. 展开一个业务场景或错误类型 Slice，解释失败文档仍在分母；
6. 将一个 Feedback Candidate 分类，演示只有 `model_error` 可勾选 Gold；
7. 创建 Promotion Decision，说明 `recommended`、`rejected`、`inconclusive`；
8. 明确 Decision 不会部署模型，生产配置仍需独立发布审批。

不要在演示中提交 `.env`、凭据、客户文档、完整预测或私有 Gold。

## PyCharm 运行

1. 将解释器设置为项目 `.venv\Scripts\python.exe`；
2. 工作目录设置为项目根目录；
3. API 运行 `run_api.py`；
4. Worker 另开一个 Run Configuration，运行 `run_extraction_worker.py`；
5. 前端通过 npm 配置运行 `frontend/package.json` 的 `dev`。

## 常见故障

### 端口已占用

`Errno 10048` 表示端口已有监听进程，不一定是错误的僵尸进程。先检查：

```powershell
Get-NetTCPConnection -LocalPort 8200 -State Listen
```

如果健康检查正常，说明 API 可能已经启动，不应再开第二份。

### queued 很久

检查：

1. UI 的 Worker 状态；
2. Worker 日志；
3. MinerU Token；
4. Run 的 `next_attempt_at` 和 error code；
5. PostgreSQL/MinIO 是否可达。

### 前端显示图片失败

前端通过 Vite Proxy 请求 API/MinIO 代理路径。若终端出现
`ECONNREFUSED 127.0.0.1:<api-port>`，说明代理目标 API 没启动或端口配置错误。

### 127.0.0.1 拒绝连接

127.0.0.1 是当前电脑的回环地址。拒绝连接通常表示目标端口没有服务监听，不是
浏览器“无法连接自己”。

## 演示前检查

- `.env` 存在且无占位密码；
- API 健康检查 200；
- Worker online；
- 前端可以登录；
- 使用合成测试文件；
- Review 有 Evidence 和 Model Run；
- 已准备一张 Invoice 加两张 Receive Note 的一对多案例；
- 终端和截图不显示 Token、密码或真实财务数据。

容器化完整演示、GitHub Actions 发布和回滚边界见
[CI/CD、容器发布与回滚](20-ci-cd-and-release.md)。
