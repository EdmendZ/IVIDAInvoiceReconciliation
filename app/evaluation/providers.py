"""Shared construction and provenance for real evaluation providers."""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version

from app.core.config import Settings
from app.domain.documents import Invoice, ReceiveNote
from app.infra.mineru_parser import MinerUPrecisionParser
from app.infra.openai_normalization_provider import OpenAINormalizationProvider


def build_real_parser(settings: Settings) -> MinerUPrecisionParser:
    return MinerUPrecisionParser.create(
        token=settings.mineru_api_token,
        base_url=settings.mineru_base_url,
        model_name=settings.mineru_model,
        language=settings.mineru_language,
        timeout_seconds=settings.mineru_timeout_seconds,
    )


def build_real_normalizer(settings: Settings) -> OpenAINormalizationProvider:
    return OpenAINormalizationProvider.create(
        api_key=settings.normalization_api_key,
        base_url=settings.normalization_base_url,
        model_name=settings.normalization_model,
        timeout_seconds=settings.normalization_timeout_seconds,
        input_cost_aud_per_million=(
            Decimal(str(settings.normalization_input_cost_aud_per_million))
            if settings.normalization_input_cost_aud_per_million is not None
            else None
        ),
        output_cost_aud_per_million=(
            Decimal(str(settings.normalization_output_cost_aud_per_million))
            if settings.normalization_output_cost_aud_per_million is not None
            else None
        ),
        max_retries=settings.normalization_max_retries,
        enable_thinking=settings.normalization_enable_thinking,
        max_output_tokens=settings.normalization_max_output_tokens,
    )


def parser_runtime_version() -> str:
    try:
        return version("mineru")
    except PackageNotFoundError:
        return "unknown"


def document_schema_version() -> str:
    schemas = {
        "invoice": Invoice.model_json_schema(),
        "receive_note": ReceiveNote.model_json_schema(),
    }
    encoded = json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()[:16]}"


def evaluation_parameters(settings: Settings) -> dict[str, object]:
    return {
        "mineru_language": settings.mineru_language,
        "normalization_enable_thinking": settings.normalization_enable_thinking,
        "normalization_max_output_tokens": settings.normalization_max_output_tokens,
        "normalization_max_retries": settings.normalization_max_retries,
        "normalization_timeout_seconds": settings.normalization_timeout_seconds,
    }
