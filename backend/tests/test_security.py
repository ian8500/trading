from __future__ import annotations

from app.auth.service import LocalAdminAuth
from app.core.config import Settings
from app.core.redaction import redact_mapping, redact_text
from argon2 import PasswordHasher


def test_live_execution_configuration_fails_closed() -> None:
    try:
        Settings(LIVE_EXECUTION_ENABLED=True)
    except ValueError as error:
        assert "LIVE_EXECUTION_ENABLED" in str(error)
    else:
        raise AssertionError("live execution unexpectedly enabled")


def test_credentials_are_redacted() -> None:
    mapping = redact_mapping({"username": "researcher", "password": "hidden", "CST": "token"})
    assert mapping == {"username": "researcher", "password": "[REDACTED]", "CST": "[REDACTED]"}
    output = redact_text("password=hidden authorization:Bearer-token")
    assert "hidden" not in output
    assert "Bearer-token" not in output


def test_local_admin_uses_opaque_session_and_csrf() -> None:
    password = " ".join(("a", "sufficiently", "long", "test", "password"))
    settings = Settings(DASHBOARD_ADMIN_PASSWORD_HASH=PasswordHasher().hash(password))
    auth = LocalAdminAuth(settings)
    result = auth.login("admin", password)
    assert result is not None
    raw_token, identity = result
    assert password not in raw_token
    assert auth.authenticate(raw_token) == identity
    assert auth.validate_csrf(identity, identity.csrf_token)
    auth.logout(raw_token)
    assert auth.authenticate(raw_token) is None
