from contextlib import contextmanager
from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_dependencies import require_reviewer
from app.domain.admin_users import AdminRole, AuthenticatedUser


TEST_REVIEWER = AuthenticatedUser(
    user_id="00000000-0000-0000-0000-000000000099",
    username="test-reviewer",
    role=AdminRole.REVIEWER,
)

TEST_ADMIN = AuthenticatedUser(
    user_id="00000000-0000-0000-0000-000000000098",
    username="test-admin",
    role=AdminRole.ADMIN,
)


def authenticated_reviewer() -> AuthenticatedUser:
    return TEST_REVIEWER


def restore_override(app: FastAPI, dependency: object, previous: object) -> None:
    if previous is None:
        app.dependency_overrides.pop(dependency, None)
    else:
        app.dependency_overrides[dependency] = previous


@contextmanager
def reviewer_client(app: FastAPI) -> Iterator[TestClient]:
    previous = app.dependency_overrides.get(require_reviewer)
    app.dependency_overrides[require_reviewer] = authenticated_reviewer
    try:
        yield TestClient(app)
    finally:
        restore_override(app, require_reviewer, previous)


@contextmanager
def admin_client(app: FastAPI) -> Iterator[TestClient]:
    previous = app.dependency_overrides.get(require_reviewer)
    app.dependency_overrides[require_reviewer] = lambda: TEST_ADMIN
    try:
        yield TestClient(app)
    finally:
        restore_override(app, require_reviewer, previous)
