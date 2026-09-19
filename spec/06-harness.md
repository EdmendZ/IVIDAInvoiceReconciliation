# 06 Harness：轻量开发约束

版本 IR-SIMPLE-1.0.3。用户已明确要求“修正 拒绝问题复杂化 继续开发”。本版取消 Docker/VM、操作系统文件级隔离、外部执行器和撤销工具凭据前提。直接使用现有环境，不安装额外平台。

## 1. 固定执行方式

1. 协调者保存当前代码基线与Spec哈希。
2. 每任务创建新执行上下文，只注入Spec、任务ID、已验收依赖及精确文件白名单，不复制讨论历史。
3. 执行者只修改白名单文件，不新增未指定模块，不改架构或Spec，不自行派生Agent。
4. 协调者独立核对diff、运行测试并验收；失败不推进后续任务，修复也使用新上下文。
5. 完成的执行上下文不再复用。审计记录保留；不声称工具凭据或操作系统进程已被物理销毁。

本版本 enforcement 固定为 diff-gate-only：白名单约束＋事后差异检查，越界变更不能通过验收。它不是操作系统写权限隔离，禁止把两者混称。Docker既不是启动条件也不是验收条件。

## 2. Spec和基线

Spec digest：spec/所有普通文件按POSIX相对路径排序；每项为 path＋NUL＋文件SHA-256＋LF，拼接UTF-8再SHA-256。拒绝符号链接。冻结证据存 `.git/ir-harness/freeze.json`（不进入代码diff），字段 spec_version/spec_sha256/baseline_commit/approval_basis/enforcement/checker_sha256。approval_basis如实引用用户指令，不冒充个人签名。checker_sha256在T00验收后由协调者补充。无需用户手工签署JSON。

执行前检查前置任务通过、基线无未提交改动、Spec哈希一致。中文界面与本次规范纳入基线，不得reset/clean丢掉。协调者可以为已验收阶段创建本地提交，不推送或部署。

## 3. 权限和测试

manifest为唯一文件白名单，路径精确到文件。检查tracked与untracked、删除、rename两端、链接、改Spec、改守卫等越界。忽略正常未跟踪构建缓存（依据既有gitignore），不得忽略业务源码。guard自身由协调者审查并保留受信版本，执行者不能修改守卫让自己通过。

T00创建守卫，协调者必须手动独立检查其diff和对抗测试；T01以后用已验收守卫验证。标准检查：任务测试、check_task_scope、check_spec_contract及git diff --check。最终运行全部前后端测试与构建。测试失败不能通过删测试、弱化断言或吞异常解决。

## 4. 决策边界

执行者遇到接口/白名单缺口，输出SPEC_CHANGE_REQUIRED及最小证据，不自行改Spec。协调者依据已授权业务目标修正文档中的遗漏或矛盾并记录版本变化；新增业务范围必须交用户决定。不得因为文档流程本身的复杂度阻塞可安全完成的工作。

## 5. 任务包

任务包只有：task_id、spec_version/spec_sha256、base_commit、spec/路径、当前任务manifest、已验收依赖、执行命令。结果写 `.harness/runs/Txx/result.json`，记录diff、命令退出码、验收场景及限制。实现者不能自己接受任务或开始下一任务。

命令argv中的${TASK_ID}/${TASK_BASE}/${RELEASE_BASE}/${FREEZE_RECORD}由协调者逐参数替换，不通过eval。status not_started在Spec中是初始计划值；实际状态以任务报告和协调者验收记录为准，执行中不修改冻结manifest。
