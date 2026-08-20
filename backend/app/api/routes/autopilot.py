from __future__ import annotations

from fastapi import APIRouter

from app.autopilot import autopilot_monitor

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


@router.get("/status")
def autopilot_status() -> dict[str, object]:
    """Return the latest automatic, non-executing research decision."""

    return autopilot_monitor.snapshot.to_payload()
