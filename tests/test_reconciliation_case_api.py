from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import (
    get_admin_repository,
    get_reconciliation_case_service,
)
from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.reconciliation import ReconciliationResult, ReconciliationSummary
from app.domain.reconciliation_cases import (
    AssignmentFilter,
    CaseDetail,
    CaseItem,
    CaseItemType,
    CaseListQuery,
    CasePage,
    CaseStatus,
    ReconciliationCase,
    ResolutionType,
)
from app.domain.reconciliation_records import ReconciliationRecord
from app.infra.database import Base
from app.infra.database_models import AdminUserRow
from app.infra.postgres_admin_repository import PostgresAdminRepository
from app.main import app
from app.services.reconciliation_case_service import CaseError, ReconciliationCaseService
from tests.auth_helpers import (
    TEST_REVIEWER,
    admin_client,
    reviewer_client,
)


CASE_ID = "case-1"
ITEM_ID = "item-1"
REVIEWER_ID = "reviewer-a"
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _detail(
    *,
    status: CaseStatus = CaseStatus.UNASSIGNED,
    revision: int = 1,
    assignee_user_id: str | None = None,
) -> CaseDetail:
    reconciliation = ReconciliationRecord(
        reconciliation_id="reconciliation-1",
        invoice_version_id="invoice-version-1",
        receive_note_version_ids=["receive-note-version-1"],
        result=ReconciliationResult(
            invoice_number="INV-001",
            receive_note_numbers=["RN-001"],
            purchase_order_match=False,
            currency_match=True,
            lines=[],
            summary=ReconciliationSummary(
                total_lines=0,
                exact_lines=0,
                tolerance_lines=0,
                mismatch_lines=0,
                invoice_only_lines=0,
                receive_note_only_lines=0,
                requires_review=True,
            ),
        ),
        created_by=TEST_REVIEWER.user_id,
        created_at=NOW,
    )
    return CaseDetail(
        case=ReconciliationCase(
            case_id=CASE_ID,
            reconciliation_id=reconciliation.reconciliation_id,
            status=status,
            assignee_user_id=assignee_user_id,
            revision=revision,
            created_by=TEST_REVIEWER.user_id,
            created_at=NOW,
        ),
        items=[
            CaseItem(
                item_id=ITEM_ID,
                case_id=CASE_ID,
                item_type=CaseItemType.PURCHASE_ORDER_CONFLICT,
                updated_at=NOW,
            )
        ],
        actions=[],
        reconciliation=reconciliation,
    )


class RecordingCaseService:
    def __init__(self, detail: CaseDetail | None = None) -> None:
        self.detail = detail or _detail()
        self.calls: list[tuple[str, object]] = []
        self.error: CaseError | None = None

    def _record(self, name: str, payload: object) -> None:
        self.calls.append((name, payload))
        if self.error is not None:
            raise self.error

    def _advance(self, **changes: object) -> None:
        case = self.detail.case.model_copy(
            update={"revision": self.detail.case.revision + 1, **changes}
        )
        self.detail = self.detail.model_copy(update={"case": case})

    def list_cases(
        self,
        query: CaseListQuery,
        *,
        user: AuthenticatedUser,
    ) -> CasePage:
        self._record("list_cases", (query, user))
        return CasePage(items=[], page=query.page, page_size=query.page_size, total=0)

    def get_detail(self, case_id: str) -> CaseDetail:
        self._record("get_detail", case_id)
        return self.detail

    def claim(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> None:
        self._record("claim", (case_id, user, expected_revision))
        self._advance(status=CaseStatus.IN_PROGRESS, assignee_user_id=user.user_id)

    def reassign(
        self,
        case_id: str,
        target_user_id: str,
        *,
        user: AuthenticatedUser,
        reason: str,
        expected_revision: int,
    ) -> None:
        self._record(
            "reassign",
            (case_id, target_user_id, user, reason, expected_revision),
        )
        self._advance(assignee_user_id=target_user_id)

    def set_resolution(
        self,
        case_id: str,
        item_id: str,
        resolution_type: ResolutionType,
        note: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> None:
        self._record(
            "set_resolution",
            (case_id, item_id, resolution_type, note, user, expected_revision),
        )
        item = self.detail.items[0].model_copy(
            update={"resolution_type": resolution_type, "resolution_note": note}
        )
        self.detail = self.detail.model_copy(update={"items": [item]})
        self._advance()

    def submit_approval(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> None:
        self._record("submit_approval", (case_id, user, expected_revision))
        self._advance(status=CaseStatus.PENDING_APPROVAL)

    def submit_void(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> None:
        self._record("submit_void", (case_id, user, expected_revision))
        self._advance(status=CaseStatus.PENDING_VOID)

    def approve(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> None:
        self._record("approve", (case_id, user, expected_revision))
        self._advance(status=CaseStatus.APPROVED)

    def return_case(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        reason: str,
        expected_revision: int,
    ) -> None:
        self._record("return_case", (case_id, user, reason, expected_revision))
        self._advance(status=CaseStatus.IN_PROGRESS)

    def void(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> None:
        self._record("void", (case_id, user, expected_revision))
        self._advance(status=CaseStatus.VOIDED)


class FakeAdminRepository:
    def list_active_reviewers(self) -> list[AuthenticatedUser]:
        return [
            AuthenticatedUser(
                user_id=REVIEWER_ID,
                username="reviewer-a",
                role=AdminRole.REVIEWER,
            )
        ]

    def is_active_reviewer(self, user_id: str) -> bool:
        return user_id == REVIEWER_ID


@contextmanager
def _service_client(
    service: RecordingCaseService,
    *,
    admin: bool = False,
) -> Iterator[TestClient]:
    previous = app.dependency_overrides.get(get_reconciliation_case_service)
    app.dependency_overrides[get_reconciliation_case_service] = lambda: service
    try:
        with (admin_client(app) if admin else reviewer_client(app)) as client:
            yield client
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_reconciliation_case_service, None)
        else:
            app.dependency_overrides[get_reconciliation_case_service] = previous


def test_list_accepts_repeated_status_filters_and_page_bounds() -> None:
    service = RecordingCaseService()
    with _service_client(service) as client:
        response = client.get(
            "/api/reconciliation-cases",
            params=[
                ("status", "pending_approval"),
                ("status", "pending_void"),
                ("assignment", "mine"),
                ("invoice_number", "INV-"),
                ("page", "2"),
                ("page_size", "100"),
            ],
        )

    assert response.status_code == 200
    query, user = service.calls[0][1]
    assert query == CaseListQuery(
        statuses=(CaseStatus.PENDING_APPROVAL, CaseStatus.PENDING_VOID),
        assignment=AssignmentFilter.MINE,
        invoice_number="INV-",
        page=2,
        page_size=100,
    )
    assert user == TEST_REVIEWER
    assert response.json() == {"items": [], "page": 2, "page_size": 100, "total": 0}


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"page": 0}, "page"),
        ({"page_size": 0}, "page_size"),
        ({"page_size": 101}, "page_size"),
    ],
)
def test_list_rejects_invalid_page_bounds(params: dict[str, int], field: str) -> None:
    with _service_client(RecordingCaseService()) as client:
        response = client.get("/api/reconciliation-cases", params=params)

    assert response.status_code == 422
    assert field in response.text


def test_detail_returns_the_full_case_read_model() -> None:
    with _service_client(RecordingCaseService()) as client:
        response = client.get(f"/api/reconciliation-cases/{CASE_ID}")

    assert response.status_code == 200
    assert response.json()["case"]["case_id"] == CASE_ID
    assert response.json()["reconciliation"]["result"]["invoice_number"] == "INV-001"


def test_reviewer_claims_and_updates_resolution() -> None:
    service = RecordingCaseService()
    with _service_client(service) as client:
        claimed = client.post(
            f"/api/reconciliation-cases/{CASE_ID}/claim",
            json={"expected_revision": 1},
        )
        updated = client.put(
            f"/api/reconciliation-cases/{CASE_ID}/items/{ITEM_ID}/resolution",
            json={
                "resolution_type": "business_exception",
                "note": "Supplier approved short delivery",
                "expected_revision": 2,
            },
        )

    assert claimed.status_code == 200
    assert claimed.json()["case"]["status"] == "in_progress"
    assert updated.status_code == 200
    assert updated.json()["case"]["revision"] == 3
    assert updated.json()["items"][0]["resolution_type"] == "business_exception"
    assert [name for name, _ in service.calls] == [
        "claim",
        "get_detail",
        "set_resolution",
        "get_detail",
    ]


def test_reviewer_cannot_approve() -> None:
    service = RecordingCaseService()
    service.error = CaseError("CASE_ADMIN_REQUIRED", "Admin role required")
    with _service_client(service) as client:
        response = client.post(
            f"/api/reconciliation-cases/{CASE_ID}/approve",
            json={"expected_revision": 1},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CASE_ADMIN_REQUIRED"


@pytest.mark.parametrize(
    (
        "path",
        "payload",
        "service_method",
        "admin",
        "initial_status",
        "expected_status",
    ),
    [
        (
            f"/{CASE_ID}/reassign",
            {
                "assignee_user_id": REVIEWER_ID,
                "reason": "Balance queue",
                "expected_revision": 1,
            },
            "reassign",
            True,
            CaseStatus.IN_PROGRESS,
            "in_progress",
        ),
        (
            f"/{CASE_ID}/submit-approval",
            {"expected_revision": 1},
            "submit_approval",
            False,
            CaseStatus.IN_PROGRESS,
            "pending_approval",
        ),
        (
            f"/{CASE_ID}/submit-void",
            {"expected_revision": 1},
            "submit_void",
            False,
            CaseStatus.IN_PROGRESS,
            "pending_void",
        ),
        (
            f"/{CASE_ID}/approve",
            {"expected_revision": 1},
            "approve",
            True,
            CaseStatus.PENDING_APPROVAL,
            "approved",
        ),
        (
            f"/{CASE_ID}/return",
            {"reason": "Clarify approval", "expected_revision": 1},
            "return_case",
            True,
            CaseStatus.PENDING_APPROVAL,
            "in_progress",
        ),
        (
            f"/{CASE_ID}/void",
            {"expected_revision": 1},
            "void",
            True,
            CaseStatus.PENDING_VOID,
            "voided",
        ),
    ],
)
def test_mutation_endpoints_return_case_detail(
    path: str,
    payload: dict[str, object],
    service_method: str,
    admin: bool,
    initial_status: CaseStatus,
    expected_status: str,
) -> None:
    service = RecordingCaseService(
        _detail(
            status=initial_status,
            assignee_user_id=TEST_REVIEWER.user_id,
        )
    )
    with _service_client(service, admin=admin) as client:
        response = client.post(
            f"/api/reconciliation-cases{path}",
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["case"]["status"] == expected_status
    assert [name for name, _ in service.calls] == [service_method, "get_detail"]


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        (
            f"/{CASE_ID}/reassign",
            {"assignee_user_id": REVIEWER_ID, "reason": "", "expected_revision": 1},
            "reason",
        ),
        (
            f"/{CASE_ID}/reassign",
            {
                "assignee_user_id": REVIEWER_ID,
                "reason": "   ",
                "expected_revision": 1,
            },
            "reason",
        ),
        (
            f"/{CASE_ID}/reassign",
            {"assignee_user_id": "", "reason": "Needed", "expected_revision": 1},
            "assignee_user_id",
        ),
        (
            f"/{CASE_ID}/reassign",
            {"assignee_user_id": "   ", "reason": "Needed", "expected_revision": 1},
            "assignee_user_id",
        ),
        (f"/{CASE_ID}/return", {"reason": "", "expected_revision": 1}, "reason"),
        (f"/{CASE_ID}/return", {"reason": "   ", "expected_revision": 1}, "reason"),
    ],
)
def test_mandatory_reassign_and_return_fields(
    path: str,
    payload: dict[str, object],
    field: str,
) -> None:
    with _service_client(RecordingCaseService(), admin=True) as client:
        response = client.post(f"/api/reconciliation-cases{path}", json=payload)

    assert response.status_code == 422
    assert field in response.text


@pytest.mark.parametrize("note", ["", "   "])
def test_resolution_requires_non_empty_note(note: str) -> None:
    with _service_client(RecordingCaseService()) as client:
        response = client.put(
            f"/api/reconciliation-cases/{CASE_ID}/items/{ITEM_ID}/resolution",
            json={
                "resolution_type": "business_exception",
                "note": note,
                "expected_revision": 1,
            },
        )

    assert response.status_code == 422
    assert "note" in response.text


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("CASE_NOT_FOUND", 404),
        ("CASE_ASSIGNEE_REQUIRED", 403),
        ("CASE_ADMIN_REQUIRED", 403),
        ("CASE_REVISION_CONFLICT", 409),
        ("CASE_ALREADY_CLAIMED", 409),
        ("CASE_REVIEWER_REQUIRED", 409),
        ("CASE_INVALID_TRANSITION", 409),
        ("CASE_ITEMS_INCOMPLETE", 409),
        ("CASE_SUBMISSION_CONFLICT", 409),
        ("CASE_TERMINAL", 409),
        ("CASE_INVALID_ASSIGNEE", 409),
        ("CASE_ITEM_NOT_FOUND", 409),
    ],
)
def test_case_errors_have_stable_code_and_status(code: str, status: int) -> None:
    service = RecordingCaseService()
    service.error = CaseError(code, "test message")
    with _service_client(service) as client:
        response = client.post(
            f"/api/reconciliation-cases/{CASE_ID}/claim",
            json={"expected_revision": 1},
        )

    assert response.status_code == status
    assert response.json()["detail"] == {"code": code, "message": "test message"}


def test_assignee_list_is_admin_only_and_safe() -> None:
    previous = app.dependency_overrides.get(get_admin_repository)
    app.dependency_overrides[get_admin_repository] = FakeAdminRepository
    try:
        with reviewer_client(app) as client:
            forbidden = client.get("/api/reconciliation-cases/assignees")
        with admin_client(app) as client:
            response = client.get("/api/reconciliation-cases/assignees")
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_admin_repository, None)
        else:
            app.dependency_overrides[get_admin_repository] = previous

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "CASE_ADMIN_REQUIRED"
    assert response.status_code == 200
    assert response.json() == [{"user_id": REVIEWER_ID, "username": "reviewer-a"}]
    assert "password_hash" not in response.text
    assert "role" not in response.text


def test_admin_repository_lists_only_active_reviewers_in_stable_order() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                AdminUserRow(
                    user_id="reviewer-z",
                    username="zeta",
                    password_hash="secret-z",
                    role="reviewer",
                    is_active=True,
                    created_at=NOW,
                ),
                AdminUserRow(
                    user_id="reviewer-a",
                    username="alpha",
                    password_hash="secret-a",
                    role="reviewer",
                    is_active=True,
                    created_at=NOW,
                ),
                AdminUserRow(
                    user_id="inactive",
                    username="inactive",
                    password_hash="secret-i",
                    role="reviewer",
                    is_active=False,
                    created_at=NOW,
                ),
                AdminUserRow(
                    user_id="admin",
                    username="admin",
                    password_hash="secret-admin",
                    role="admin",
                    is_active=True,
                    created_at=NOW,
                ),
            ]
        )
        session.commit()

    repository = PostgresAdminRepository(factory)

    assert [user.username for user in repository.list_active_reviewers()] == [
        "alpha",
        "zeta",
    ]
    assert repository.is_active_reviewer("reviewer-a") is True
    assert repository.is_active_reviewer("inactive") is False
    assert repository.is_active_reviewer("admin") is False


def test_real_service_detail_uses_the_joined_read_model() -> None:
    class DetailRepository:
        def get_detail(self, case_id: str) -> CaseDetail | None:
            return _detail() if case_id == CASE_ID else None

    service = ReconciliationCaseService(
        DetailRepository(),
        active_reviewer_reader=FakeAdminRepository(),
    )

    assert service.get_detail(CASE_ID).reconciliation.result.invoice_number == "INV-001"
    with pytest.raises(CaseError) as captured:
        service.get_detail("missing")
    assert captured.value.code == "CASE_NOT_FOUND"
