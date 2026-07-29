from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.documents import Invoice, ReceiveNote


class MatchStatus(StrEnum):
    EXACT = "exact"
    WITHIN_TOLERANCE = "within_tolerance"
    MISMATCH = "mismatch"
    INVOICE_ONLY = "invoice_only"
    RECEIVE_NOTE_ONLY = "receive_note_only"


class ReconciliationTolerance(BaseModel):
    quantity: Decimal = Field(default=Decimal("0"), ge=0)
    unit_price: Decimal = Field(default=Decimal("0.01"), ge=0)
    amount: Decimal = Field(default=Decimal("0.02"), ge=0)


class ReconciliationRequest(BaseModel):
    invoice: Invoice
    receive_notes: list[ReceiveNote] = Field(min_length=1)
    tolerance: ReconciliationTolerance = Field(default_factory=ReconciliationTolerance)


class LineComparison(BaseModel):
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
    total_lines: int
    exact_lines: int
    tolerance_lines: int
    mismatch_lines: int
    invoice_only_lines: int
    receive_note_only_lines: int
    requires_review: bool


class ReconciliationResult(BaseModel):
    invoice_number: str
    receive_note_numbers: list[str]
    purchase_order_match: bool | None
    currency_match: bool
    lines: list[LineComparison]
    summary: ReconciliationSummary

