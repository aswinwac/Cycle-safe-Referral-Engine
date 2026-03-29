from fastapi import APIRouter, Request, Response, status

from csre.db.neo4j import neo4j_healthcheck
from csre.db.postgres import postgres_healthcheck
from csre.db.redis import redis_healthcheck
from csre.schemas.envelope import success_response

router = APIRouter(tags=["health"])


def _overall_status(checks: dict[str, str]) -> str:
    return "ok" if all(value == "ok" for value in checks.values()) else "degraded"


async def _dependency_statuses(request: Request) -> dict[str, str]:
    app_state = request.app.state
    postgres_ok = await postgres_healthcheck(app_state.postgres_engine)
    neo4j_ok = await neo4j_healthcheck(app_state.neo4j_driver)
    redis_ok = await redis_healthcheck(app_state.redis)
    return {
        "postgres": "ok" if postgres_ok else "error",
        "neo4j": "ok" if neo4j_ok else "error",
        "redis": "ok" if redis_ok else "error",
    }


@router.get("/health/live")
async def liveness():
    return success_response({"status": "ok", "checks": {"liveness": "ok"}})


@router.get("/health")
async def health(request: Request, response: Response):
    checks = await _dependency_statuses(request)
    overall = _overall_status(checks)
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return success_response({**checks, "status": overall})


@router.get("/health/ready")
async def readiness(request: Request, response: Response):
    checks = await _dependency_statuses(request)
    overall = _overall_status(checks)
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return success_response({**checks, "status": overall})

