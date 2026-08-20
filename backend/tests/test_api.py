from __future__ import annotations

from collections.abc import Generator
from typing import cast

import pytest
from app.auth.dependencies import auth_service
from app.database.base import Base
from app.database.session import get_db
from app.main import app
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def test_db() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    old_hash = auth_service.settings.DASHBOARD_ADMIN_PASSWORD_HASH
    admin_input = " ".join(("local", "test", "administrator", "input"))
    auth_service.settings.DASHBOARD_ADMIN_PASSWORD_HASH = PasswordHasher().hash(admin_input)
    with TestClient(app) as test_client:
        test_client.headers["X-Test-Admin-Input"] = admin_input
        yield test_client
    auth_service.settings.DASHBOARD_ADMIN_PASSWORD_HASH = old_hash
    app.dependency_overrides.clear()


def test_public_config_never_contains_credentials(client: TestClient) -> None:
    response = client.get("/api/v1/config/public")
    assert response.status_code == 200
    body = response.json()
    assert body["ig_environment"] == "DEMO"
    assert "password" not in str(body).lower()
    assert "api_key" not in str(body).lower()


def test_health_fails_closed_when_database_is_unreachable(client: TestClient) -> None:
    original = app.dependency_overrides[get_db]

    def broken_db() -> Generator[Session, None, None]:
        class UnreachableDatabase:
            def execute(self, _statement: object) -> None:
                raise RuntimeError("database unavailable")

        yield cast(Session, UnreachableDatabase())

    app.dependency_overrides[get_db] = broken_db
    try:
        response = client.get("/api/v1/health")
    finally:
        app.dependency_overrides[get_db] = original
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "unhealthy"


def test_state_change_requires_session_and_csrf(client: TestClient) -> None:
    assert client.post("/api/v1/risk/profile", json={"profile": "Conservative"}).status_code == 401
    admin_input = client.headers["X-Test-Admin-Input"]
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": admin_input},
    )
    assert login.status_code == 200
    assert login.cookies.get("trading_admin_session")
    csrf = login.json()["csrf_token"]
    missing_csrf = client.post("/api/v1/risk/profile", json={"profile": "Conservative"})
    assert missing_csrf.status_code == 403
    updated = client.post(
        "/api/v1/risk/profile",
        json={"profile": "Conservative", "taperEnabled": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200
    status = client.get("/api/v1/risk/status").json()
    assert status["profile"] == "Conservative"
    assert status["taperEnabled"] is True


def test_live_readiness_is_informational_only(client: TestClient) -> None:
    body = client.get("/api/v1/live-readiness").json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["liveExecutionEnabled"] is False


def test_autopilot_is_automatic_and_cannot_execute_orders(client: TestClient) -> None:
    response = client.get("/api/v1/autopilot/status")
    assert response.status_code == 200
    body = response.json()
    assert body["automaticMonitoring"] is True
    assert body["state"] in {"STAY_IN_CASH", "HUMAN_REVIEW_REQUIRED"}
    assert body["orderExecutionEnabled"] is False
    assert body["demoTradingEnabled"] is False
    assert body["liveTradingEnabled"] is False


@pytest.mark.parametrize(
    ("path", "payload"),
    (
        (
            "/api/v1/backtests",
            {
                "dateFrom": "2025-01-01",
                "dateTo": "2025-02-01",
                "startingCapital": 500,
                "instruments": ["GBP/USD"],
                "strategies": ["Quant Baseline"],
                "riskProfile": "Standard",
                "costModel": "REALISTIC",
                "resolution": "1d",
                "compounding": True,
                "riskTaper": False,
            },
        ),
        (
            "/api/v1/replay/sessions",
            {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-02T00:00:00Z",
                "startingCapital": 500,
                "strategy": "Quant Baseline",
                "riskProfile": "Standard",
                "costModel": "REALISTIC",
            },
        ),
        ("/api/v1/backtests/nonexistent/cancel", {}),
    ),
)
def test_research_mutations_require_session_and_csrf(
    client: TestClient, path: str, payload: dict[str, object]
) -> None:
    assert client.post(path, json=payload).status_code == 401
    admin_input = client.headers["X-Test-Admin-Input"]
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": admin_input},
    )
    assert login.status_code == 200
    assert client.post(path, json=payload).status_code == 403
