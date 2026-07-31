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


def authenticated_reviewer() -> AuthenticatedUser:
    return TEST_REVIEWER


@contextmanager
def reviewer_client(app: FastAPI) -> Iterator[TestClient]:
    previous = app.dependency_overrides.get(require_reviewer)
    app.dependency_overrides[require_reviewer] = authenticated_reviewer
    try:
        yield TestClient(app)
    finally:
        if previous is None:
            app.dependency_overrides.pop(require_reviewer, None)
        else:
            app.dependency_overrides[require_reviewer] = previous
