"""机器抽取结果以及与其绑定的 Evidence/Validation Issue。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.domain.documents import DocumentType
from app.domain.normalization import FieldEvidence
from app.domain.validation import ValidationIssue


class DraftValidationState(StrEnum):
    """机器草稿是否带有阻止批准的确定性问题。"""

    REVIEWABLE = "reviewable"
    BLOCKED = "blocked"


class DocumentDraft(BaseModel):
    """尚未由人工确认的规范化文档快照。

    Draft 可以带着警告或阻断问题进入审核区，但它不代表可信财务事实，也不能
    直接参加对账。人工开始审核时会据此创建独立的 DocumentVersion。
    """

    draft_id: str
    run_id: str
    task_id: str
    document_type: DocumentType
    normalized_json: dict
    validation_state: DraftValidationState
    created_at: datetime
    updated_at: datetime


class DraftBundle(BaseModel):
    """一次读取中返回 Draft、字段证据和规则问题。"""

    draft: DocumentDraft
    evidence: list[FieldEvidence]
    issues: list[ValidationIssue]
