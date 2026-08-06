# CI/CD、容器发布与回滚

## 目标和非生产边界

本仓库使用 GitHub Actions 模拟企业项目的持续集成、容器交付和版本发布流程。
自动化只运行在 GitHub-hosted Runner 和临时 Service Container 中，不连接现有服务器，
也不调用 MinerU、模型 API 或其他付费服务。该流程可以证明代码和交付物可重复构建，
但不代表已经完成生产部署、容量规划、灾备或安全加固。

## Pull Request CI

`.github/workflows/ci.yml` 同时服务 Pull Request、`main`、手动运行和可复用
Workflow。它包含四个固定 Job：

- `quality`：编译检查、文档同步检查和空白检查；
- `backend`：排除真实 PostgreSQL 用例后的后端测试；
- `postgres-integration`：迁移、真实数据库测试、回退再升级和 Alembic 检查；
- `frontend`：Vitest、TypeScript 类型检查和 Vite 构建。

后端和 PostgreSQL 测试报告作为 JUnit Artifact 保留 7 天。Fork PR 不需要仓库
Secret，因此不会获得发布权限。

## PostgreSQL Service Container

`postgres-integration` 使用 PostgreSQL Service Container `postgres:18` 和一次性
测试凭据。`DATABASE_URL` 与 `IVIDA_TEST_POSTGRES_URL` 都指向 Runner 内的临时数据库，
保证 `tests/test_postgres_reconciliation_case_integration.py` 真正执行而不是跳过。
Job 结束后 Service Container 自动销毁。

## 本地 Docker Compose 演示

本地演示包含 PostgreSQL、MinIO、一次性 Migration、API、Worker 和 Frontend：

```powershell
Copy-Item .env.compose.example .env.compose
docker compose --env-file .env.compose up --build -d
uv run python tools/smoke_compose.py
docker compose --env-file .env.compose down
```

需要连同数据卷清理时使用 `docker compose --env-file .env.compose down -v`。
`.env.compose.example` 只包含本地演示凭据，不能复制为生产配置。

## Tag、GHCR 与 GitHub Release

推送符合 `v*` 的 Tag 会先复用完整 CI，然后构建 API、Worker、Frontend 三个候选
镜像。候选镜像必须通过 Compose Smoke 和 Trivy 高危/严重漏洞扫描，之后 Workflow
才登录 GHCR 并推送版本标签和 `sha-<短提交号>` 标签。流程不创建语义含糊的
`:latest` 标签。

手动运行 Release Workflow 时必须输入语义版本，例如 `v0.2.0-rc.1`，产物会标记
为 GitHub pre-release。Tag 触发的发布是正常 Release。两种入口都使用触发提交作为
Release target。

## 镜像 Digest 与 Alembic revision

`release-manifest.md` 记录完整 Git Commit、当前 Alembic revision，以及三个镜像
Digest。部署或回滚时优先使用 Digest，避免同名标签后来指向不同内容。发布前应确认
三个镜像的 Digest 都存在且数据库只有一个 Alembic head。

## 应用回滚

应用回滚只切换 API、Worker 和 Frontend 到上一份已验证 Manifest 中记录的镜像
Digest，然后重新执行 Smoke Test。Compose 演示可以设置上一版本的
`IVIDA_IMAGE_TAG` 并叠加 `compose.release.yaml` 验证。

数据库迁移与应用镜像回滚是两件事。应用回滚前应确认旧应用是否兼容当前 Schema；
如果不兼容，应使用前向修复迁移或经过单独评审的恢复方案。

## 为什么不自动 downgrade 数据库

Release Workflow 不自动 downgrade 数据库。自动回退可能删除列、约束或业务数据，
其风险远高于切换无状态应用镜像。CI 中的 `alembic downgrade -1` 仅针对一次性测试
数据库，用于证明迁移具备基本可逆性，不能当作生产回滚授权。

## Secret 与 Fork PR

Pull Request CI 使用仓库内容读取权限和临时本地凭据，不保存真实数据库密码、MinIO
密钥、SSH 凭据或模型 Token。GHCR 登录只发生在受保护的 Release Job 中，并使用
短期 `GITHUB_TOKEN`。不得把真实 Secret 写入 Workflow、Compose、Artifact、日志或
`.env.compose.example`。

## 失败诊断

1. `quality` 失败：先运行文档同步工具和 `git diff --check`；
2. `backend` 失败：下载 JUnit Artifact 并在本地复现对应 pytest 命令；
3. `postgres-integration` 失败：检查 Service Container 健康状态、迁移输出和
   `IVIDA_TEST_POSTGRES_URL`；
4. Compose Smoke 失败：先保存 `docker compose logs --no-color`，再执行清理；
5. Trivy 失败：定位产生漏洞的基础镜像或依赖，升级后重新构建，不跳过扫描；
6. GHCR 或 Release 失败：确认前面的 CI、Smoke、扫描均已成功，再检查 Job 权限。

## GitHub Branch Protection 设置

公开仓库应为 `main` 配置规则：要求 Pull Request、禁止直接推送、要求分支为最新，
并把 `quality`、`backend`、`postgres-integration`、`frontend` 以及两个 CodeQL 语言
分析设为必需检查。是否要求审批人数由仓库所有者根据演示需要手动设置；Workflow
不会自动修改仓库规则。

## Artifact 与镜像保留策略

JUnit Artifact 保留 7 天。GHCR 保留有 Release 依据的语义版本和 SHA 标签；临时
候选包的清理由仓库所有者显式批准，自动化不删除发布证据。Release Manifest 应与
对应 Release 一起长期保留，便于面试演示、审计和确定性回滚。
