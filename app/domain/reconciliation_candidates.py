from typing import Literal

from pydantic import BaseModel, Field


class CandidateSignal(BaseModel):
    code: str
    outcome: Literal["match", "conflict", "unknown"]
    message: str
    weight: int


class ReconciliationCandidate(BaseModel):
    receive_note_version_id: str
    document_number: str
    purchase_order_number: str | None = None
    supplier_name: str | None = None
    document_date: str | None = None
    score: int = Field(ge=0, le=100)
    confidence: Literal["high", "medium", "low"]
    recommended: bool
    signals: list[CandidateSignal]
