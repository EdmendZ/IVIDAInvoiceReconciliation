from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.documents import DocumentType, Invoice, ReceiveNote
from app.domain.normalization import FieldEvidence, NormalizationResult
from app.domain.parsing import ParseResult
from app.infra.external_errors import ExternalServiceError
from app.services.prompt_version import prompt_version


class NormalizationSchemaError(ValueError):
    pass


class NormalizedDocumentEnvelope(BaseModel):
    document: dict
    evidence: list[FieldEvidence]


class OpenAINormalizationProvider:
    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        client: Any,
        model_name: str,
        timeout_seconds: int = 120,
        input_cost_aud_per_million: Decimal | None = None,
        output_cost_aud_per_million: Decimal | None = None,
    ) -> None:
        self._client = client
        self.model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._input_cost = input_cost_aud_per_million
        self._output_cost = output_cost_aud_per_million
        prompt_dir = Path(__file__).parents[1] / "resources" / "prompts"
        self._system_prompt = (
            prompt_dir / "normalize_document_system.txt"
        ).read_text(encoding="utf-8")
        self._user_template = (
            prompt_dir / "normalize_document_user.txt"
        ).read_text(encoding="utf-8")
        self._prompt_version = prompt_version(
            self._system_prompt,
            self._user_template,
        )

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    @classmethod
    def create(
        cls,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_seconds: int = 120,
        input_cost_aud_per_million: Decimal | None = None,
        output_cost_aud_per_million: Decimal | None = None,
    ) -> "OpenAINormalizationProvider":
        if not api_key or not model_name:
            raise ValueError("Normalization API key and model are required")
        from openai import OpenAI

        options: dict[str, Any] = {"api_key": api_key}
        if base_url:
            options["base_url"] = base_url
        return cls(
            client=OpenAI(**options),
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            input_cost_aud_per_million=input_cost_aud_per_million,
            output_cost_aud_per_million=output_cost_aud_per_million,
        )

    def normalize(
        self,
        *,
        document_type: DocumentType,
        parse_result: ParseResult,
    ) -> NormalizationResult:
        document_model = (
            Invoice if document_type == DocumentType.INVOICE else ReceiveNote
        )
        schema = {
            "document": document_model.model_json_schema(),
            "evidence": {
                "type": "array",
                "items": FieldEvidence.model_json_schema(),
            },
        }
        user_prompt = self._user_template.format(
            document_type=document_type.value,
            schema=json.dumps(schema, ensure_ascii=False),
            markdown=parse_result.markdown,
            content_blocks=json.dumps(
                parse_result.content_blocks,
                ensure_ascii=False,
            ),
        )
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                timeout=self._timeout_seconds,
            )
            raw_text = response.choices[0].message.content or ""
            raw = json.loads(raw_text)
            envelope = NormalizedDocumentEnvelope.model_validate(raw)
            self._reject_empty_identifiers(envelope.document)
            document = document_model.model_validate(envelope.document)
        except (json.JSONDecodeError, ValidationError, IndexError, AttributeError) as exc:
            raise NormalizationSchemaError(
                "Normalization response did not match the required schema"
            ) from exc
        except NormalizationSchemaError:
            raise
        except Exception as exc:
            raise ExternalServiceError(
                "NORMALIZATION_REQUEST_FAILED",
                "Document normalization request failed",
                retryable=True,
            ) from exc

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        return NormalizationResult(
            document=document,
            evidence=envelope.evidence,
            raw_response=raw,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_aud=self._estimate_cost(
                input_tokens,
                output_tokens,
            ),
        )

    @staticmethod
    def _reject_empty_identifiers(document: dict) -> None:
        for field in ("document_number", "purchase_order_number"):
            if document.get(field) == "":
                raise NormalizationSchemaError(
                    f"{field} must be null when absent"
                )
        for party_name in ("supplier", "location"):
            party = document.get(party_name)
            if isinstance(party, dict) and party.get("business_number") == "":
                raise NormalizationSchemaError(
                    f"{party_name}.business_number must be null when absent"
                )

    def _estimate_cost(
        self,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> Decimal | None:
        if (
            input_tokens is None
            or output_tokens is None
            or self._input_cost is None
            or self._output_cost is None
        ):
            return None
        return (
            Decimal(input_tokens) * self._input_cost
            + Decimal(output_tokens) * self._output_cost
        ) / Decimal(1_000_000)
