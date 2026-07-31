import json
from types import SimpleNamespace

import pytest

from app.domain.documents import DocumentType
from app.domain.parsing import ParseResult
from app.infra.openai_normalization_provider import (
    NormalizationSchemaError,
    OpenAINormalizationProvider,
)


class FakeCompletions:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.last_request = None

    def create(self, **kwargs):
        self.last_request = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(self.payload),
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )


def _client(payload: dict):
    completions = FakeCompletions(payload)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        completions_fixture=completions,
    )


def _parse_result() -> ParseResult:
    return ParseResult(
        provider="mineru",
        model_name="vlm",
        markdown="# TAX INVOICE\nInvoice SCF-INV-260701",
        content_blocks=[],
        tables=[],
        page_count=1,
    )


def _payload(purchase_order_number="PO-100") -> dict:
    return {
        "document": {
            "document_type": "invoice",
            "document_number": "SCF-INV-260701",
            "purchase_order_number": purchase_order_number,
            "currency": "AUD",
            "items": [
                {
                    "description": "Mozzarella",
                    "quantity": "2",
                    "unit_price": "10.00",
                    "line_total": "20.00",
                }
            ],
        },
        "evidence": [
            {
                "field_path": "document_number",
                "value": "SCF-INV-260701",
                "page": 1,
                "source_text": "Invoice SCF-INV-260701",
            }
        ],
    }


def test_invoice_response_becomes_valid_document() -> None:
    client = _client(_payload())
    provider = OpenAINormalizationProvider(
        client=client,
        model_name="normalizer-test",
    )
    result = provider.normalize(
        document_type=DocumentType.INVOICE,
        parse_result=_parse_result(),
    )
    assert result.document.document_number == "SCF-INV-260701"
    assert result.evidence[0].field_path == "document_number"
    assert result.input_tokens == 100
    assert provider.prompt_version.startswith("sha256:")
    assert client.completions_fixture.last_request["extra_body"] == {
        "enable_thinking": False
    }
    assert "max_completion_tokens" not in client.completions_fixture.last_request


def test_explicit_output_limit_is_forwarded_for_non_json_compatible_models() -> None:
    client = _client(_payload())
    provider = OpenAINormalizationProvider(
        client=client,
        model_name="normalizer-test",
        max_output_tokens=4096,
    )

    provider.normalize(
        document_type=DocumentType.INVOICE,
        parse_result=_parse_result(),
    )

    assert (
        client.completions_fixture.last_request["max_completion_tokens"]
        == 4096
    )


def test_missing_identifier_must_be_null_not_empty_string() -> None:
    provider = OpenAINormalizationProvider(
        client=_client(_payload(purchase_order_number="")),
        model_name="normalizer-test",
    )
    with pytest.raises(NormalizationSchemaError):
        provider.normalize(
            document_type=DocumentType.INVOICE,
            parse_result=_parse_result(),
        )
