"""Machine-to-machine API for authoritative Taptouch receiving snapshots."""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies import get_taptouch_receiving_import_service
from app.api.integration_auth import (
    TaptouchIntegrationPrincipal,
    authenticate_taptouch_principal,
)
from app.domain.taptouch_receiving import TaptouchReceivingPayload
from app.services.taptouch_receiving_import_service import (
    ReceivingIdentityConflict,
    ReceivingVersionConflict,
    TaptouchReceivingImportService,
)

router = APIRouter(
    prefix="/api/integrations/taptouch",
    tags=["Taptouch integration"],
    dependencies=[Depends(authenticate_taptouch_principal)],
)


@router.post("/receiving-records", status_code=status.HTTP_201_CREATED)
def import_receiving_record(
    payload: TaptouchReceivingPayload,
    response: Response,
    principal: TaptouchIntegrationPrincipal = Depends(
        authenticate_taptouch_principal
    ),
    service: TaptouchReceivingImportService = Depends(
        get_taptouch_receiving_import_service
    ),
) -> dict:
    if not principal.allows(
        payload.external_tenant_id,
        payload.external_store_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "integration_scope_forbidden",
                "message": "Credential is not authorized for this tenant/store",
            },
        )
    try:
        outcome = service.import_record(
            payload,
            integration_principal=principal.name,
        )
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
