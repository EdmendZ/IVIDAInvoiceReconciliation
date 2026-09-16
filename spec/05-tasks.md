# 05 任务、模块责任与文件权限

机器权威清单是 [tasks.json](tasks.json)。下表定义工作内容和验收含义；两者不一致时停止。任务严格串行 T00→T11，每个任务单独新执行上下文；协调者负责验收和推进。

任何任务只能读冻结 Spec＋本任务列出的输入实现＋直接依赖的已验收代码/报告；可只读检查现有源码寻找证据，但不得把旧聊天、旧计划作为新需求。整个 spec/ 对执行 Agent 只读。不自动读取 .env、个人配置、数据库备份或 evaluation_data 私有样本。

## T00：建立 Harness 检查基座

输入：本包、冻结记录、已提交基线。输出：tools/check_task_scope.py、tools/check_spec_contract.py、固定测试、CI 守卫。不得实现业务功能。

接口：`check_task_scope.py --task Txx --base <sha> --spec-root spec --evidence <external-json>`；扫描 tracked diff、untracked、删除、rename 两端、符号链接/junction、子模块、路径大小写与路径穿越。依赖外部冻结记录校验自身 SHA 和 Spec SHA；未指定 base/task/freeze 直接失败。每个文件必须属于 task 的 modify/create 列表；create 路径若在 base 已存在也失败；modify 若不存在也失败。空 diff 除明确无代码任务外失败。

`check_spec_contract.py --spec-root spec`：验证 task ID 唯一、依赖 DAG、精确路径无 glob、目录闭合、命令与测试路径存在/已列创建任务、接口/任务引用无悬空。不得用扫描关键字取代真实行为验收。

恶意样例：../ 越界、绝对外盘、rename 出圈、未跟踪新模块、改白名单、删除锁文件、修改检查器、符号链接逃逸必须全部拒绝。T00 本身由人/外部调度器预置规则检查，不允许用自己新写的脚本证明自己可信。T00 验收后协调者保留检查器哈希及受信版本；后续任务不可修改或绕过。

## T01：领域 DTO 与 Protocol

实现 02/03 的所有枚举、数据类型、联合类型和端口，前后端契约同名映射。固定边界校验：decimal string、reason 长度、selection 去重、acknowledged true、extra forbid。不得做 DB 或 HTTP 实现。

提供 WorkspaceService/Repository/Worker 后续所需类型；类型定义必须覆盖 requests、responses、source metadata、sync/tick；禁止“以后再补接口”。验证 JSON 往返不改变英文数据和 Decimal 精度。

## T02：纯匹配与核对规则

实现 04 两个纯函数、身份规范化；修复旧 ValidationService 的部分税额误报；不修改旧 reconciliation_service 的业务算法。验证中文不坍缩、单位不跨加、缺价 unverified、PO 一对多、候选歧义、主体冲突、重复发票确认规则的输入校验辅助。

## T03：持久化与事务

v1.0.3：新增表必须同步数据库字典，避免原有文档测试在后续任务基线失败。

v1.0.2 补全：仅在领域 DTO 增加 ConfirmationView.invoice_number / receive_note_numbers，并补往返测试；编号由不可变修订读取，供已有 CSV 导出使用。

实现八张 ws 表和单一迁移、PostgresWorkspaceRepository 全部端口；intake 原 Task/Run 同事务，确认/claims/actions/幂等同事务。旧上游 Repository 加 scope advisory lock，除此不改其数据契约。JSONB/唯一约束/不可变表触发器在真实 PostgreSQL 验证；SQLite 测试不能代替。

新增索引/约束只能是 02 所列，触发器禁止修改 ws_revisions/ws_previews/ws_confirmations/ws_actions 的既存行；允许 rollback 和迁移 downgrade 清空空表，不允许应用绕过触发器。

## T04：自动同步与后台进程

实现 WorkspaceWorker.tick/run_forever、入口；配置 WORKSPACE_ENABLED、WORKSPACE_TENANT_ID、WORKSPACE_STORE_ID 和 `workspace_poll_seconds=3` 固定默认、不得通过业务 API 改动。entrypoint 处理 SIGTERM/KeyboardInterrupt，当前短事务结束后退出；无外部模型调用。启动脚本、停止脚本、compose 增加 workspace-worker，复用后端镜像，不能新增第四个镜像。

同步 latest Draft/上游来源、失效预览、重启恢复、并发 CAS、100批次、runtime 15秒阈值；worker_online 定义 last_sync_at 距服务器当前时间≤15秒。所有时间测试使用注入时钟或固定时间，不真实 sleep。

## T05：用户用例与导出

DocumentUploadService 抽取 prepare_upload，旧 upload 行为保持；WorkspaceService 完整实现所有方法，不引入新服务。export/source 在此文件内，不另建模块。确认重新验证而非信任客户端 outcome；重开释放 claims；差异待核实与完成明确区分。

prepare_upload 不写 SQL；intake 返回失败时按02处理新对象补偿。mutation 不通过旧 HTTP 调用，不调用多个独立 commit 的旧 Repository 模拟事务。

## T06：HTTP 与旧入口治理

实现03全部路由、依赖装配和设置开关；旧写入口在 workspace enabled 时拒绝，旧读和模型 Worker 正常。工作台 POST 入参禁止 tenant/store；认证、404隐藏范围外对象、限文件大小、CSRF/session 行为沿用原系统，不开通配 CORS。不引入新的身份系统。

GET 全只读；数据库/对象存储异常映射03错误，不吞掉输入冲突为503；上传返回201，retry202，confirm201。PUT 同样必须幂等。OpenAPI 自动生成与冻结契约逐项核验。

## T07：前端类型、客户端与展示函数

实现03前端 interfaces/methods，沿用中文 i18n 样式。统一 Idempotency-Key、金额字符串、409刷新但保留输入；不做任何自动批准。不修改 API status 枚举或提交中文字段名。

## T08：单页工作台

实现两个页面及 App 切换：WORKSPACE_ENABLED 由 `/api/workspace/runtime` 响应的 enabled 字段告知前端（runtime 在 disabled 仍可查，新增必填 enabled bool）；disabled 沿用旧 UI。enabled 主导航及单页行为遵从01。收货单能先上传、无发票也能在收货列表看见。批量上传不在范围，禁止自行添加。

复用 StructuredDocumentEditor，但增加可选 readOnly prop（默认false），已完成/权威收货全部只读；以输入变动后保存触发预览，不自动提交未保存字段。旧历史组件增加 readOnly prop（默认false）隐藏写按钮但保留查询和 CSV；Case 不再可认领。

## T09：端到端回归与文档同步

v1.0.3：允许修改现有 CI，将新 PostgreSQL 测试接入专用以 `_workspace_test` 结尾的 CI 数据库，显式设置 WORKSPACE_TEST_DATABASE_URL，不能只依赖默认 skip。

仅在任务白名单内补 acceptance fixtures、API/worker 实际数据库串联测试和操作文档。此任务无权修复业务代码：失败必须给原任务开启新的修复上下文，保持原文件白名单，验收后再运行 T09。

所有外部模型使用固定 fake；真实 PostgreSQL 用独立测试数据库；严禁把集成测试指向用户已有演示/生产数据库。环境变量 `WORKSPACE_TEST_DATABASE_URL` 必须显式提供，数据库名以 `_workspace_test` 结尾，否则测试拒绝启动。默认本地未配置时 skip，但发布门禁不允许 skip。

## T10：Harness 对抗验收

独立新会话验证越权拒绝、修改守卫拒绝、污染基线拒绝、失败任务不合并、候选分数不能绕过人工确认。只可改指定测试/说明，不可更改守卫来让恶意样例通过。

## T11：最终集成验收

只读业务代码；固定场景检查、生成证据，不自动部署/切换开关。执行全量 pytest、前端测试/build、文档同步、diff检查、Spec契约/任务权限检查。发现失败退回原任务，不以“最后收尾”为由扩大权限。

## 任务报告（每任务唯一输出）

`.harness/runs/Txx/result.json`：task_id、spec_version、spec_sha256、base_commit、candidate_commit/null、changed_files、commands（argv/exit_code/log_sha256）、acceptance_ids、known_limits、status=passed/failed/blocked。该文件是审计产物，不改变批准状态；可信调度器复制到外部证据库并签署 accepted/rejected。stdout 日志存外部证据库，不任意写 repo。禁止凭“tests passed”字符串替代命令退出码。

新增文件必须使用清单 create；只列 modify 不代表可创建同名替代文件。`.harness/runs` 的报告路径同样逐任务精确列出，不授予整个目录写权限。
