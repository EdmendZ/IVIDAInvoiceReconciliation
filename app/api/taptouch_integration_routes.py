"""Machine-to-machine API for authoritative Taptouch receiving snapshots."""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies import get_taptouch_receiving_import_service
from app.api.integration_auth import require_taptouch_token
from app.domain.taptouch_receiving import TaptouchReceivingPayload
from app.services.taptouch_receiving_import_service import (
    ReceivingIdentityConflict,
    ReceivingVersionConflict,
    TaptouchReceivingImportService,
)

router = APIRouter(
    prefix="/api/integrations/taptouch",
    tags=["Taptouch integration"],
    dependencies=[Depends(require_taptouch_token)],
)


@router.post("/receiving-records", status_code=status.HTTP_201_CREATED)
def import_receiving_record(
    payload: TaptouchReceivingPayload,
    response: Response,
    service: TaptouchReceivingImportService = Depends(
        get_taptouch_receiving_import_service
    ),
) -> dict:
    try:
        outcome = service.import_record(payload)
    except ReceivingVersionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "stale_external_version", "message": str(exc)},
        ) from exc
    except ReceivingIdentityConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "external_version_conflict", "message": str(exc)},
        ) from exc
    response.status_code = (
        status.HTTP_201_CREATED if outcome.created else status.HTTP_200_OK
    )
    return {
        "created": outcome.created,
        "version": outcome.version.model_dump(mode="json"),
    }
