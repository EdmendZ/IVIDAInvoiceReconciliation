# 演示与源码导读

## 五分钟演示

1. 运行 `setup_dev_admin.py`，复制临时账号。
2. 运行 `run_local_demo.py`，打开 <http://127.0.0.1:5274>。
3. 上传英文 Invoice，说明系统后台自动处理，用户可以离开页面。
4. 展示“等待关联单据”，再上传 Receive Note。
5. 打开详情，同页展示原件、英文业务字段、候选和逐行差异。
6. 展示缺失价格为“未核验”；一致结果仍要求一次确认。
7. 确认并导出 CSV，再重开说明旧快照没有被覆盖。

这是本机演示 Pilot，不宣称真实 TapTouch 已接入、模型达到生产准确率或系统会自动付款。

## 项目讲解

问题不是“能不能 OCR”，而是非结构化供应商发票和门店收货事实到达时间不同，且模型
可能漏字段。解决方案把不确定抽取和确定性财务规则分开：MinerU/模型生成可审核修订，
工作台用保守规则自动关联，用户只在最后确认一次。PostgreSQL 保存状态和审计，MinIO
保存原件，HttpOnly Session 和门店范围控制访问。

关键取舍：不用消息中间件维持 Pilot；用数据库租约和轮询获得可恢复性；不让模型决定
差异；不把未知价格补零；不为单店用户复制企业审批状态机。

## 源码阅读顺序

1. `app/domain/workspace.py`：状态、命令和错误。
2. `app/services/workspace_service.py`：工作台用例边界。
3. `app/infra/postgres_workspace_repository.py`：事务、锁、幂等和快照。
4. `app/services/workspace_matching.py` 与 `workspace_comparison.py`：纯规则。
5. `app/workers/workspace_worker.py`：自动同步和预览。
6. `app/api/workspace_routes.py`：HTTP、认证和错误映射。
7. `frontend/src/workspace/`：中文列表和聚合详情页。

旧流程源码用于理解演进历史：`document_upload_service.py`、`extraction_worker.py`、
`validation_service.py`、`review_service.py`、`candidate_matching_service.py`、
`reconciliation_service.py`、`postgres_reconciliation_repository.py` 和
`evaluation/runner.py`。工作台启用后这些写流程不会重新暴露给日常用户。
