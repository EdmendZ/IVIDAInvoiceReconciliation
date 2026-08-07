"""Authentication dependency for machine-to-machine integration endpoints."""

import hmac
import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TaptouchIntegrationScope:
    external_tenant_id: str
    external_store_id: str


@dataclass(frozen=True)
class TaptouchIntegrationPrincipal:
    """Authenticated caller and the upstream locations it may write."""

    name: str
    allowed_scopes: tuple[TaptouchIntegrationScope, ...]
    unrestricted_legacy: bool = False

    def allows(self, external_tenant_id: str, external_store_id: str) -> bool:
        if self.unrestricted_legacy:
            return True
        requested = TaptouchIntegrationScope(external_tenant_id, external_store_id)
        return requested in self.allowed_scopes


@dataclass(frozen=True)
class _ConfiguredCredential:
    principal: TaptouchIntegrationPrincipal
    token: str = field(repr=False)


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _parse_scoped_credentials(raw: str) -> tuple[_ConfiguredCredential, ...]:
    """Parse environment-provided credentials; any malformed entry fails closed."""

    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(values, list) or not values:
        return ()

    credentials: list[_ConfiguredCredential] = []
    tokens: set[str] = set()
    principal_names: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            return ()
        name = _non_empty_string(value.get("principal"))
        token = _non_empty_string(value.get("token"))
        scope_values = value.get("allowed_scopes")
        if (
            name is None
            or len(name) > 255
            or token is None
            or not isinstance(scope_values, list)
        ):
            return ()
        if not scope_values or token in tokens or name in principal_names:
            return ()

        scopes: list[TaptouchIntegrationScope] = []
        for scope_value in scope_values:
            if not isinstance(scope_value, dict):
                return ()
            tenant_id = _non_empty_string(scope_value.get("external_tenant_id"))
            store_id = _non_empty_string(scope_value.get("external_store_id"))
            if tenant_id is None or store_id is None:
                return ()
            scopes.append(TaptouchIntegrationScope(tenant_id, store_id))

        tokens.add(token)
        principal_names.add(name)
        credentials.append(
            _ConfiguredCredential(
                principal=TaptouchIntegrationPrincipal(name, tuple(scopes)),
                token=token,
            )
        )
    return tuple(credentials)


def _configured_credentials(settings: Settings) -> tuple[_ConfiguredCredential, ...]:
    scoped_raw = settings.taptouch_integration_credentials_json.strip()
    if scoped_raw:
        return _parse_scoped_credentials(scoped_raw)

    legacy_token = settings.taptouch_integration_token
    if not legacy_token:
        return ()
    return (
        _ConfiguredCredential(
            principal=TaptouchIntegrationPrincipal(
                name="legacy-integration-token",
                allowed_scopes=(),
                unrestricted_legacy=True,
            ),
            token=legacy_token,
        ),
    )


def authenticate_taptouch_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> TaptouchIntegrationPrincipal:
    """Authenticate a configured caller without exposing any supplied token."""

    configured_credentials = _configured_credentials(settings)
    supplied = credentials.credentials if credentials is not None else ""
    correct_scheme = credentials is not None and credentials.scheme.lower() == "bearer"
    matched: TaptouchIntegrationPrincipal | None = None
    if correct_scheme:
        for configured in configured_credentials:
            if hmac.compare_digest(
                supplied.encode("utf-8"),
                configured.token.encode("utf-8"),
            ):
                matched = configured.principal

    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid integration credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return matched
