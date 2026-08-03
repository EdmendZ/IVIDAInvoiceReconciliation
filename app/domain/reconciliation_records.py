"""一次已持久化核对的版本引用与完整结果。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.domain.reconciliation import ReconciliationResult

if TYPE_CHECKING:
    from app.domain.reconciliation_cases import ReconciliationCaseBundle


class ReconciliationRecord(BaseModel):
    """把不可变输入版本、操作者、时间和核对结果绑定在一起。"""

    reconciliation_id: str
    invoice_version_id: str
    receive_note_version_ids: list[str] = Field(min_length=1)
    result: ReconciliationResult
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReconciliationPersistenceBundle:
    """应用层预先分配的、必须在同一事务中保存的完整写模型。"""

    record: ReconciliationRecord
    line_result_ids: list[str]
    case: ReconciliationCaseBundle | None
