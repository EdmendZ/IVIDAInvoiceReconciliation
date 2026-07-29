from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentType(StrEnum):
    INVOICE = "invoice"
    RECEIVE_NOTE = "receive_note"


class Party(BaseModel):
    name: str
    business_number: str | None = None
    address: str | None = None


class LineItem(BaseModel):
    line_number: str | None = None
    sku: str | None = None
    description: str
    quantity: Decimal = Field(gt=0)
    unit: str | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    tax_amount: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = Field(default=None, ge=0)


class BusinessDocument(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_type: DocumentType
    document_number: str
    document_date: date | None = None
    purchase_order_number: str | None = None
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    supplier: Party | None = None
    location: Party | None = None
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax_total: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, ge=0)
    items: list[LineItem] = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_currency(self) -> BusinessDocument:
        self.currency = self.currency.upper()
        return self


class Invoice(BusinessDocument):
    document_type: DocumentType = DocumentType.INVOICE

    @model_validator(mode="after")
    def require_invoice_type(self) -> Invoice:
        if self.document_type != DocumentType.INVOICE:
            raise ValueError("Invoice document_type must be 'invoice'")
        return self


class ReceiveNote(BusinessDocument):
    document_type: DocumentType = DocumentType.RECEIVE_NOTE

    @model_validator(mode="after")
    def require_receive_note_type(self) -> ReceiveNote:
        if self.document_type != DocumentType.RECEIVE_NOTE:
            raise ValueError("ReceiveNote document_type must be 'receive_note'")
        return self

