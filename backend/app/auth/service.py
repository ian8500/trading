from __future__ import annotations

import hashlib
import hmac
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import Settings

SESSION_COOKIE = "trading_admin_session"
SESSION_TTL = timedelta(hours=8)


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    username: str
    csrf_token: str
    expires_at: datetime


class LocalAdminAuth:
    """Process-local opaque sessions; no password or broker credential is persisted."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._hasher = PasswordHasher()
        self._sessions: dict[str, SessionIdentity] = {}
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return bool(self.settings.DASHBOARD_ADMIN_PASSWORD_HASH)

    def login(self, username: str, password: str) -> tuple[str, SessionIdentity] | None:
        if not self.configured or not hmac.compare_digest(
            username, self.settings.DASHBOARD_ADMIN_USERNAME
        ):
            self._dummy_verify(password)
            return None
        try:
            valid = self._hasher.verify(self.settings.DASHBOARD_ADMIN_PASSWORD_HASH, password)
        except (VerifyMismatchError, InvalidHashError):
            return None
        if not valid:
            return None
        raw_token = secrets.token_urlsafe(48)
        identity = SessionIdentity(
            username=username,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=datetime.now(UTC) + SESSION_TTL,
        )
        with self._lock:
            self._sessions[self._digest(raw_token)] = identity
        return raw_token, identity

    def authenticate(self, raw_token: str | None) -> SessionIdentity | None:
        if not raw_token:
            return None
        digest = self._digest(raw_token)
        with self._lock:
            identity = self._sessions.get(digest)
            if identity and identity.expires_at <= datetime.now(UTC):
                self._sessions.pop(digest, None)
                return None
            return identity

    def logout(self, raw_token: str | None) -> None:
        if raw_token:
            with self._lock:
                self._sessions.pop(self._digest(raw_token), None)

    @staticmethod
    def validate_csrf(identity: SessionIdentity, supplied: str | None) -> bool:
        if supplied is None:
            return False
        return hmac.compare_digest(identity.csrf_token, supplied)

    @staticmethod
    def _digest(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode()).hexdigest()

    def _dummy_verify(self, password: str) -> None:
        # Keep unconfigured/unknown-user timing closer to a normal Argon2 verification.
        dummy = "$argon2id$v=19$m=65536,t=3,p=4$MDAwMDAwMDAwMDAwMDAwMA$Mh7qz60MUF6wqg4uWrEtWg"
        with suppress(VerifyMismatchError, InvalidHashError):
            self._hasher.verify(dummy, password)
