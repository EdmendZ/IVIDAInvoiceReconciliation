from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.reconciliation import ReconciliationResult


class ReconciliationRecord(BaseModel):
    reconciliation_id: str
    invoice_version_id: str
    receive_note_version_ids: list[str] = Field(min_length=1)
    result: ReconciliationResult
    created_by: str
    created_at: datetime
