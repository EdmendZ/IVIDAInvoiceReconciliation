from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.domain.documents import BusinessDocument, DocumentType


@dataclass(frozen=True)
class ExtractionProviderResult:
    raw_output: dict
    normalized_document: BusinessDocument
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_aud: Decimal | None = None


class ExtractionProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def extract(
        self,
        *,
        document_type: DocumentType,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ExtractionProviderResult: ...


class ExtractionProviderDisabled(RuntimeError):
    pass


class DisabledExtractionProvider:
    @property
    def provider_name(self) -> str:
        return "disabled"

    @property
    def model_name(self) -> str:
        return "disabled"

    def extract(
        self,
        *,
        document_type: DocumentType,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ExtractionProviderResult:
        raise ExtractionProviderDisabled(
            "No extraction model is configured. Set MODEL_PROVIDER before extraction."
        )

