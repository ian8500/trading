from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.auth.dependencies import auth_service
from app.auth.service import SESSION_COOKIE

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


@router.get("/status")
def auth_status(
    trading_admin_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, object]:
    identity = auth_service.authenticate(trading_admin_session)
    return {
        "configured": auth_service.configured,
        "authenticated": identity is not None,
        "username": identity.username if identity else None,
        "csrf_token": identity.csrf_token if identity else None,
        "expires_at": identity.expires_at.isoformat() if identity else None,
    }


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict[str, object]:
    result = auth_service.login(payload.username, payload.password)
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    raw_token, identity = result
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=False,  # Local HTTP default; TLS deployments must override at the reverse proxy.
        samesite="strict",
        max_age=int((identity.expires_at - datetime.now(UTC)).total_seconds()),
        path="/api/v1",
    )
    response.set_cookie(
        "csrf_token",
        identity.csrf_token,
        httponly=False,
        secure=False,
        samesite="strict",
        max_age=int((identity.expires_at - datetime.now(UTC)).total_seconds()),
        path="/",
    )
    return {
        "authenticated": True,
        "username": identity.username,
        "csrf_token": identity.csrf_token,
        "expires_at": identity.expires_at.isoformat(),
    }


@router.post("/logout")
def logout(
    response: Response,
    trading_admin_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, bool]:
    auth_service.logout(trading_admin_session)
    response.delete_cookie(SESSION_COOKIE, path="/api/v1")
    response.delete_cookie("csrf_token", path="/")
    return {"authenticated": False}
