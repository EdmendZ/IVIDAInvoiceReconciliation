"""后台审核用户、角色与数据库 Session 的领域契约。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AdminRole(StrEnum):
    """后台权限角色；Reviewer 处理业务，Admin 还可管理账号。"""

    REVIEWER = "reviewer"
    ADMIN = "admin"


class AdminUser(BaseModel):
    """包含 Password Hash 的持久化用户模型，不返回给浏览器。"""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    username: str
    password_hash: str
    role: AdminRole
    is_active: bool
    created_at: datetime


class AuthenticatedUser(BaseModel):
    """认证成功后可安全返回给 API/UI 的最小用户信息。"""

    user_id: str
    username: str
    role: AdminRole


class AdminSession(BaseModel):
    """数据库保存的 Session Token Hash 与过期时间。"""

    session_token_hash: str
    user_id: str
    expires_at: datetime
    created_at: datetime
