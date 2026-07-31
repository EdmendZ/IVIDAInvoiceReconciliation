from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

from app.domain.documents import BusinessDocument, DocumentType
from app.domain.parsing import ParseResult


class FieldEvidence(BaseModel):
    field_path: str
    value: str | None = None
    page: int | None = Field(default=None, ge=1)
    source_text: str
    block_id: str | None = None
    table_id: str | None = None
    row_index: int | None = Field(default=None, ge=0)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)


class NormalizationResult(BaseModel):
    document: BusinessDocument
    evidence: list[FieldEvidence] = Field(default_factory=list)
    raw_response: dict
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_aud: Decimal | None = Field(default=None, ge=0)


class NormalizationProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    def normalize(
        self,
        *,
        document_type: DocumentType,
        parse_result: ParseResult,
    ) -> NormalizationResult: ...
