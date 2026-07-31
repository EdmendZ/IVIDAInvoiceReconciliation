"""Receive Note 候选分数及每个可解释信号。"""

from typing import Literal

from pydantic import BaseModel, Field


class CandidateSignal(BaseModel):
    """一个匹配、冲突或未知信号及其规则权重。"""

    code: str
    outcome: Literal["match", "conflict", "unknown"]
    message: str
    weight: int


class ReconciliationCandidate(BaseModel):
    """供审核人员选择的 Receive Note 候选，不代表统计概率。"""

    receive_note_version_id: str
    document_number: str
    purchase_order_number: str | None = None
    supplier_name: str | None = None
    document_date: str | None = None
    score: int = Field(ge=0, le=100)
    confidence: Literal["high", "medium", "low"]
    recommended: bool
    signals: list[CandidateSignal]
