"""一次已持久化核对的版本引用与完整结果。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.reconciliation import ReconciliationResult


class ReconciliationRecord(BaseModel):
    """把不可变输入版本、操作者、时间和核对结果绑定在一起。"""

    reconciliation_id: str
    invoice_version_id: str
    receive_note_version_ids: list[str] = Field(min_length=1)
    result: ReconciliationResult
    created_by: str
    created_at: datetime
