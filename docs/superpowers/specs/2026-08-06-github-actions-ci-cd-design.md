# GitHub Actions 企业化 CI/CD 展示设计

## 背景与目标

IVIDA Invoice Reconciliation 已具备文档上传、异步抽取、人工审核、确定性对账、
Reconciliation Case 处理闭环、数据库迁移以及后端和前端自动化测试。本阶段的目标
不是建设真实生产运维环境，而是让公开 GitHub 仓库能够可信地展示企业级持续集成、
容器化交付、版本发布和回滚设计。

成功结果应证明：每次代码变更都经过稳定且可重复的验证；PostgreSQL 专属约束和
并发行为在真实数据库中测试；发布制品能够追溯到 Commit、Migration 和不可变镜像；
整个过程不依赖真实服务器、付费模型调用或生产 Secret。

## 范围

### 包含

- GitHub Actions Pull Request 和 `main` 分支 CI；
- GitHub-hosted Ubuntu Runner；
- Python、前端、文档和真实 PostgreSQL 分层验证；
- API、Worker、Frontend 三个容器运行目标；
- Docker Compose 可复现演示环境；
- GHCR 版本化镜像；
- Tag 驱动的 GitHub Release；
- 镜像 Smoke Test；
- Dependabot、CodeQL 和最终镜像漏洞扫描；
- Branch Protection 建议；
- Migration、发布和回滚 Runbook。

### 不包含

- 连接或修改任何真实服务器；
- 自建 GitHub Actions Runner；
- SSH 自动部署；
- VPN、企业内网和防火墙建设；
- Kubernetes、Helm、Terraform 或云厂商部署；
- 多节点、高可用、自动扩容和灾备中心；
- 真实 MinerU、LLM 或生产 MinIO 调用；
- 正式 SLA、值班告警和生产运维承诺。

## 核心原则

1. **公开仓库优先。** 使用标准 GitHub-hosted Runner，避免额外服务器成本。
2. **确定性优先。** PR 不调用外部付费服务，模型和 MinerU 使用 Fake、Fixture 或缓存。
3. **真实数据库边界。** PostgreSQL Trigger、JSONB、Migration、锁和并发必须在临时
   PostgreSQL 18 中验证，SQLite 不能替代这一层。
4. **制品不可变。** Release 记录镜像 Digest、Commit SHA 和 Alembic revision。
5. **数据库谨慎回滚。** 应用可切换旧镜像，数据库不自动 downgrade；Schema 变更优先
   向后兼容。
6. **最小权限。** CI 默认只读，只有 Release Job 获得 Package 和 Release 写权限。
7. **诚实展示。** 仓库可以声明完成 CI/CD 模拟和可复现交付，不能声明已生产部署。

## Workflow 架构

### CI Workflow

`.github/workflows/ci.yml` 在 Pull Request、Push 到 `main` 和手动触发时运行。
同一分支的新运行取消旧运行，避免浪费额度。Workflow 包含四个并行 Job。

#### `quality`

- Python `compileall`；
- 文档代码映射同步检查；
- Git whitespace 检查；
- 必要的静态契约检查。

#### `backend`

- 安装项目要求的 Python 和 `uv`；
- 按锁文件安装依赖并使用缓存；
- 运行不依赖外部服务的完整 pytest；
- 默认排除显式标记的真实 PostgreSQL Job，避免重复执行。

#### `postgres-integration`

- 在 Ubuntu Runner 中启动 PostgreSQL 18 Service Container；
- 使用仅限本次 Job 的测试账号和数据库；
- 执行 `alembic upgrade head`；
- 设置 `IVIDA_TEST_POSTGRES_URL` 并运行真实 PostgreSQL 集成测试；
- 执行 downgrade 到上一 revision 后重新 upgrade；
- 执行 `alembic current`、`heads` 和 `check`；
- 不连接任何长期数据库。

#### `frontend`

- 安装锁定主版本的 Node；
- 使用 `npm ci`；
- 运行 Vitest；
- 运行 TypeScript typecheck；
- 运行 Vite production build。

所有必需 Job 都是 Branch Protection 的 Required Status Checks。个人公开仓库不强制
第二人审批，但禁止绕过失败检查直接合并。

### Release Workflow

`.github/workflows/release.yml` 由 `v*` Tag 或手动预发布触发，顺序如下：

1. 校验 Tag 与版本格式；
2. 确认源 Commit 的 CI 已通过；
3. 构建 API、Worker、Frontend 镜像；
4. 在临时 PostgreSQL/MinIO 环境中启动 Migration、API、Worker 和 Frontend；
5. 执行镜像级 Smoke Test；
6. 扫描最终镜像；
7. 以版本 Tag 和 `sha-<short-sha>` 标记并推送 GHCR；
8. 记录镜像 Digest 与 Alembic revision；
9. 生成部署清单和 Release Notes；
10. 创建 GitHub Release。

失败时不创建正式 Release、不更新稳定标签，也不自动执行数据库 downgrade。

## 容器与演示环境

### 后端镜像

一个多阶段后端 Dockerfile 产生两个运行 Target：

- `api`：运行 Uvicorn/FastAPI；
- `worker`：运行独立 Extraction Worker。

两个 Target 共享锁定依赖和代码层，但使用不同启动命令。运行阶段使用非 root 用户，
不包含 `.env`、测试缓存、上传数据、Git 历史或模型响应缓存。

### 前端镜像

前端 Dockerfile 使用 Node 构建，再把 `dist` 复制到最小静态 Web Server 镜像。
静态服务器提供前端路由，并将 `/api` 转发到 API 服务。

### Docker Compose

根目录 `compose.yaml` 包含：

- `postgres`；
- `minio`；
- 一次性 `migrate`；
- `api`；
- `worker`；
- `frontend`。

PostgreSQL 和 MinIO 通过健康检查后，`migrate` 执行 `alembic upgrade head`；只有
Migration 成功，API 与 Worker 才启动。API 和 Worker 不并发自行迁移。

默认演示命令是 `docker compose up --build`。演示环境使用独立本地 Volume 和演示
凭据；真实 Provider 必须显式开启，不能成为默认启动前提。

## 测试策略

测试分为四层：

1. **纯逻辑层：** 对账规则、Case 工厂、状态机、权限、Evaluation 和展示规则；
2. **Adapter/API 层：** FastAPI 契约、Session、Repository、CSV 和前端组件；
3. **PostgreSQL 层：** Trigger、JSONB、复合约束、Migration、并发认领、revision 和
   事务回滚；
4. **镜像 Smoke 层：** Migration、服务启动、Health、OpenAPI、前端首页和数据库
   revision。

并发测试使用显式同步点，不依赖不稳定的固定 `sleep`。测试固定时区和输入时间，
不依赖执行顺序，也不访问付费 API。

## 安全与依赖治理

- CI Job 默认 `contents: read`；
- Release 仅使用 `contents: write` 和 `packages: write`；
- Fork PR 不获得 Repository Secret；
- CI 使用临时测试凭据，不使用真实 PostgreSQL、MinIO、MinerU 或模型 Secret；
- Dependabot 每周检查 Python、npm、Docker 和 GitHub Actions；
- CodeQL 扫描 Python 与 JavaScript/TypeScript；
- 最终 Docker Image 进行漏洞扫描；
- 第三方 Action 使用固定版本，并由 Dependabot 更新；
- 日志和 Artifact 不包含 `.env`、业务原件、数据库 Dump 或模型完整响应。

## 镜像与版本规则

每个服务至少产生两个标签：

- 发布版本，例如 `v0.2.0`；
- Commit 标签，例如 `sha-abc1234`。

Release 使用镜像 Digest 作为不可变引用。默认不覆盖语义不明确的 `latest`；正式版本
可以显式更新 `stable`。版本遵循语义化版本，Feature Branch 经 PR 合并到始终可构建
的 `main`，再由 Tag 触发 Release，不增加长期 `develop` 或 `release/*` 分支。

## 回滚策略

应用回滚通过选择上一 Release 的镜像 Digest 完成。数据库 Migration 优先采用
expand/contract 思路：先增加兼容结构，等旧应用退出后再删除旧结构。Release Workflow
不自动 downgrade 数据库；若 Migration 已写入新格式数据，盲目 downgrade 可能造成
数据损坏。

Release Notes 必须记录：Commit SHA、镜像 Digest、Alembic revision、环境字段变化、
Migration 风险、已知限制和应用回滚命令。

## Artifact 与成本控制

- 测试报告和失败日志保留 7 天；
- 前端 `dist` 不重复长期保存，以容器镜像为准；
- 正式 Release 清单长期保存；
- 正式版本镜像长期保存，普通 SHA 镜像按保留策略清理；
- 不上传 MinerU ZIP、真实单据或数据库 Dump；
- 使用公开仓库的标准 GitHub-hosted Runner，不配置自建 Runner。

## 面试展示口径

可以如实表述：项目使用 GitHub Actions 对纯逻辑、真实 PostgreSQL 和容器运行进行
分层验证；PR 不调用付费模型；Tag 产生可追溯的版本化镜像和 Release；Migration 与
应用回滚采取不同策略。

不能声称：系统已经生产部署、支持高可用、承载真实企业流量、具备正式 SLA 或已完成
灾备体系。

## 验收标准

- PR 自动运行并通过四类 Required Checks；
- 普通后端测试不连接外部服务；
- PostgreSQL 集成测试在 CI 中实际执行而非跳过；
- 空库 upgrade、downgrade/re-upgrade 和 Alembic check 通过；
- 前端测试、typecheck 和 production build 通过；
- API、Worker、Frontend 三个镜像可以重复构建；
- Compose 一条命令可以启动完整演示环境；
- 镜像 Smoke Test 不调用付费服务并稳定通过；
- `v*` Tag 生成 GHCR 镜像和 GitHub Release；
- Release 可以追溯 Commit、Migration 和镜像 Digest；
- 仓库中没有真实服务器地址、密码、API Key 或生产配置；
- 任何 Workflow 都不连接或修改现有服务器。

