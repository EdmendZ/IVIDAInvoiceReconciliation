from fastapi import APIRouter

from app.core.config import get_settings
from app.domain.reconciliation import ReconciliationRequest, ReconciliationResult
from app.services.reconciliation_service import reconcile

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@router.get("/reconciliations/example")
def reconciliation_example() -> dict:
    return {
        "invoice": {
            "document_number": "INV-1001",
            "document_date": "2026-07-29",
            "purchase_order_number": "PO-7788",
            "currency": "AUD",
            "supplier": {"name": "Example Food Supplier"},
            "items": [
                {
                    "sku": "CHEESE-01",
                    "description": "Mozzarella Cheese 2kg",
                    "quantity": "10",
                    "unit": "case",
                    "unit_price": "25.00",
                    "line_total": "250.00",
                }
            ],
        },
        "receive_notes": [
            {
                "document_number": "RN-5001",
                "document_date": "2026-07-28",
                "purchase_order_number": "PO-7788",
                "currency": "AUD",
                "items": [
                    {
                        "sku": "CHEESE-01",
                        "description": "Mozzarella Cheese 2kg",
                        "quantity": "10",
                        "unit": "case",
                        "unit_price": "25.00",
                        "line_total": "250.00",
                    }
                ],
            }
        ],
    }


@router.post("/reconciliations/compare", response_model=ReconciliationResult)
def compare_documents(request: ReconciliationRequest) -> ReconciliationResult:
    return reconcile(request)

