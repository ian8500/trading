from __future__ import annotations

from fastapi import Cookie, Header, HTTPException, status

from app.auth.service import SESSION_COOKIE, LocalAdminAuth, SessionIdentity
from app.core.config import get_settings

auth_service = LocalAdminAuth(get_settings())


def current_admin(
    trading_admin_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> SessionIdentity:
    identity = auth_service.authenticate(trading_admin_session)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="administrator login required"
        )
    return identity


def csrf_admin(
    trading_admin_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    x_csrf_token: str | None = Header(default=None),
) -> SessionIdentity:
    session_identity = auth_service.authenticate(trading_admin_session)
    if session_identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="administrator login required"
        )
    if not auth_service.validate_csrf(session_identity, x_csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid CSRF token")
    return session_identity
