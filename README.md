# IVIDA Invoice Reconciliation

IVIDA 发票（Invoice）与收货单（Receive Note）比对原型。该项目与客服知识库项目完全分离，只复用同一套基础设施服务。

## 当前阶段

阶段 1 已建立：

- 独立 FastAPI 服务，默认端口 `8200`
- Invoice / Receive Note 标准 JSON 数据模型
- 支持“一张发票对应多张收货单”的确定性行项目比对
- 数量、单价、金额容差与差异分类
- PDF、PNG、JPEG 原件上传与安全格式校验
- MinIO 原件存储与 PostgreSQL 抽取任务持久化
- PostgreSQL、MinIO 和模型供应商的独立配置命名
- 健康检查、示例接口和自动化测试

当前可以上传原件并创建任务，但尚未执行 OCR/模型抽取。比对接口的输入仍是已经结构化的 JSON。

## 启动

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

真实上传前，需要复制 `.env.example` 为 `.env`，填写 PostgreSQL 连接和当前 MinIO 的有效账号。可以复用项目2的 MinIO 服务器参数，但必须保留：

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@YOUR_HOST:5432/ivida_invoice_reconciliation
MINIO_BUCKET_NAME=ivida-invoice-documents
```

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
