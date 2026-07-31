"""SQLAlchemy Engine、Declarative Base 与 Session Factory 配置。"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM Row 的共同 Declarative Base。"""

    pass


@lru_cache
def get_engine() -> Engine:
    """按 Settings 创建进程级 Engine，并配置连接超时与预检查。"""

    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": settings.database_connect_timeout_seconds,
        },
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """返回短生命周期事务使用的 Session Factory。"""

    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )
