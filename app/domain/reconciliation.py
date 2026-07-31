"""一对多核对请求、逐行差异和汇总结果的领域契约。"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.documents import Invoice, ReceiveNote


class MatchStatus(StrEnum):
    """一条聚合商品行相对于 Invoice 的核对分类。"""

    EXACT = "exact"
    WITHIN_TOLERANCE = "within_tolerance"
    MISMATCH = "mismatch"
    INVOICE_ONLY = "invoice_only"
    RECEIVE_NOTE_ONLY = "receive_note_only"


class ReconciliationTolerance(BaseModel):
    """数量、加权单价和金额允许的绝对差值。"""

    quantity: Decimal = Field(default=Decimal("0"), ge=0)
    unit_price: Decimal = Field(default=Decimal("0.01"), ge=0)
    amount: Decimal = Field(default=Decimal("0.02"), ge=0)


class ReconciliationRequest(BaseModel):
    """一张 Invoice 与至少一张 Receive Note 的核对输入。"""

    invoice: Invoice
    receive_notes: list[ReceiveNote] = Field(min_length=1)
    tolerance: ReconciliationTolerance = Field(default_factory=ReconciliationTolerance)


class LineComparison(BaseModel):
    """一条商品键的发票值、聚合收货值、差值与解释。"""

    match_key: str
    sku: str | None
    description: str
    invoice_quantity: Decimal
    received_quantity: Decimal
    quantity_difference: Decimal
    invoice_unit_price: Decimal | None
    received_unit_price: Decimal | None
    unit_price_difference: Decimal | None
    invoice_amount: Decimal | None
    received_amount: Decimal | None
    amount_difference: Decimal | None
    status: MatchStatus
    reasons: list[str] = Field(default_factory=list)


class ReconciliationSummary(BaseModel):
    """按差异类型计数，并给出是否需要人工继续处理。"""

    total_lines: int
    exact_lines: int
    tolerance_lines: int
    mismatch_lines: int
    invoice_only_lines: int
    receive_note_only_lines: int
    requires_review: bool


class ReconciliationResult(BaseModel):
    """一次纯规则核对的完整、可序列化输出。"""

    invoice_number: str
    receive_note_numbers: list[str]
    purchase_order_match: bool | None
    currency_match: bool
    lines: list[LineComparison]
    summary: ReconciliationSummary
