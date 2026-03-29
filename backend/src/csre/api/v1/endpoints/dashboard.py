from fastapi import APIRouter, Depends, Query
from csre.schemas.envelope import success_response
from csre.modules.dashboard.service import DashboardService, get_dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/metrics")
async def get_metrics(
    window: str = Query(default="24h"),
    service: DashboardService = Depends(get_dashboard_service)
):
    result = await service.get_metrics(window)
    return success_response(result)

@router.get("/fraud-panel")
async def get_fraud_panel(
    page: int = Query(default=1),
    limit: int = Query(default=20),
    service: DashboardService = Depends(get_dashboard_service)
):
    result = await service.get_fraud_panel(page, limit)
    return success_response(result)

@router.get("/activity-feed")
async def get_activity_feed(
    limit: int = Query(default=50),
    service: DashboardService = Depends(get_dashboard_service)
):
    result = await service.get_activity_feed(limit)
    return success_response(result)

@router.get("/graph/{user_id}")
async def get_graph(
    user_id: str,
    depth: int = Query(default=3),
    service: DashboardService = Depends(get_dashboard_service)
):
    result = await service.get_graph(user_id, depth)
    return success_response(result)
