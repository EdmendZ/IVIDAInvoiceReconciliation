from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AdminRole(StrEnum):
    REVIEWER = "reviewer"
    ADMIN = "admin"


class AdminUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    username: str
    password_hash: str
    role: AdminRole
    is_active: bool
    created_at: datetime


class AuthenticatedUser(BaseModel):
    user_id: str
    username: str
    role: AdminRole


class AdminSession(BaseModel):
    session_token_hash: str
    user_id: str
    expires_at: datetime
    created_at: datetime
