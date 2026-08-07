from app.domain.documents import Invoice, ReceiveNote
from app.services.candidate_matching_service import assess_candidate


def _invoice() -> Invoice:
    return Invoice.model_validate(
        {
            "document_number": "INV-1001",
            "document_date": "2026-07-10",
            "purchase_order_number": "PO-SYD-1042",
            "currency": "AUD",
            "supplier": {"name": "Sydney Cheese Foods"},
            "location": {"name": "Sydney CBD"},
            "items": [
                {
                    "sku": "CHEESE-01",
                    "description": "Mozzarella Cheese",
                    "quantity": "10",
                },
                {
                    "sku": "FLOUR-02",
                    "description": "Pizza Flour",
                    "quantity": "5",
                },
            ],
        }
    )


def test_strong_candidate_is_recommended_with_explanations() -> None:
    note = ReceiveNote.model_validate(
        {
            "document_number": "RN-5001",
            "document_date": "2026-07-08",
            "purchase_order_number": "PO-SYD-1042",
            "currency": "AUD",
            "supplier": {"name": "Sydney Cheese Foods"},
            "location": {"name": "Sydney CBD"},
            "items": [
                {
                    "sku": "CHEESE-01",
                    "description": "Mozzarella Cheese",
                    "quantity": "10",
                },
                {
                    "sku": "FLOUR-02",
                    "description": "Pizza Flour",
                    "quantity": "5",
                },
            ],
        }
    )

    result = assess_candidate(
        invoice=_invoice(),
        receive_note=note,
        receive_note_version_id="note-v1",
        source_kind=DocumentSourceKind.TAPTOUCH_RECEIVING,
        trust_method=DocumentTrustMethod.UPSTREAM_AUTHORITATIVE,
        external_store_id="store-1",
        external_receiving_id="receiving-1",
        external_version=3,
        upstream_updated_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    assert result.score == 100
    assert result.confidence == "high"
    assert result.recommended is True
    assert result.source_kind == DocumentSourceKind.TAPTOUCH_RECEIVING
    assert result.external_store_id == "store-1"
    assert result.external_version == 3
    assert {signal.code for signal in result.signals} >= {
        "purchase_order_match",
        "supplier_match",
        "location_match",
        "currency_match",
        "date_proximity",
        "item_overlap",
    }


def test_po_conflict_prevents_recommendation() -> None:
    note = ReceiveNote.model_validate(
        {
            "document_number": "RN-OTHER",
            "document_date": "2026-07-08",
            "purchase_order_number": "PO-MEL-9999",
            "currency": "AUD",
            "supplier": {"name": "Sydney Cheese Foods"},
            "location": {"name": "Sydney CBD"},
            "items": [
                {
                    "sku": "CHEESE-01",
                    "description": "Mozzarella Cheese",
                    "quantity": "10",
                }
            ],
        }
    )

    result = assess_candidate(
        invoice=_invoice(),
        receive_note=note,
        receive_note_version_id="note-v2",
    )

    assert result.recommended is False
    assert any(
        signal.code == "purchase_order_mismatch"
        and signal.outcome == "conflict"
        for signal in result.signals
    )


def test_same_document_number_blocks_misclassified_invoice() -> None:
    source = _invoice().model_dump(mode="json")
    source["document_type"] = "receive_note"
    note = ReceiveNote.model_validate(source)

    result = assess_candidate(
        invoice=_invoice(),
        receive_note=note,
        receive_note_version_id="wrong-type-v1",
    )

    assert result.score <= 10
    assert result.confidence == "low"
    assert result.recommended is False
    assert result.signals[0].code == "same_document_number"
from datetime import UTC, datetime

from app.domain.document_sources import DocumentSourceKind, DocumentTrustMethod
