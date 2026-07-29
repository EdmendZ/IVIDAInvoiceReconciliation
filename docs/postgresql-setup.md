# PostgreSQL 连接与初始化

## 项目配置

复制 `.env.example` 为 `.env`，然后配置：

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@YOUR_HOST:5432/ivida_invoice_reconciliation
DATABASE_CONNECT_TIMEOUT_SECONDS=3
```

不要提交 `.env`。项目的 `.gitignore` 已排除该文件。

## 初始化

在 PyCharm 中右键根目录的 `init_database.py` 并运行。脚本会：

1. 连接 PostgreSQL 内置的 `postgres` 数据库。
2. 检查并创建 `ivida_invoice_reconciliation` 数据库。
3. 运行 Alembic 迁移，创建 `extraction_tasks` 等业务表。

运行数据库初始化后，再启动 `run_api.py`。

## 端口拒绝连接

如果 `5432` 返回 connection refused，需要在 PostgreSQL 所在服务器检查：

- PostgreSQL 服务或容器是否正在运行。
- Docker 是否映射了 `5432:5432`。
- `postgresql.conf` 的 `listen_addresses` 是否包含需要监听的网络接口。
- `pg_hba.conf` 是否只允许可信客户端 IP 登录。
- 系统防火墙或云安全组是否仅向当前开发机 IP 放行 TCP `5432`。

不要将 PostgreSQL 无限制开放给整个公网。修改服务端配置后需要重启 PostgreSQL。

