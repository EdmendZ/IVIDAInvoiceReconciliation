"""Authentication dependency for machine-to-machine integration endpoints."""

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


def require_taptouch_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    """Require the configured bearer token without exposing it in errors or logs."""

    configured = settings.taptouch_integration_token
    valid = (
        credentials is not None
        and credentials.scheme.lower() == "bearer"
        and bool(configured)
        and hmac.compare_digest(credentials.credentials, configured)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid integration credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
