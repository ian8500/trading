from fastapi import APIRouter

from app.api.routes import (
    auth,
    backtests,
    events,
    health,
    ig_demo,
    portfolio,
    readiness,
    replay,
    risk,
    strategies,
    system,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(risk.router)
api_router.include_router(system.router)
api_router.include_router(readiness.router)
api_router.include_router(events.router)
api_router.include_router(strategies.router)
api_router.include_router(backtests.router)
api_router.include_router(portfolio.router)
api_router.include_router(replay.router)
api_router.include_router(ig_demo.router)
