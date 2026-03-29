from typing import AsyncIterator
from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from csre.db.postgres import get_db_session
from csre.modules.dashboard.repository import DashboardRepository
from csre.modules.dashboard.schemas import MetricsResponse, FraudPanelResponse, ActivityFeedResponse, GraphResponse
from datetime import datetime

class DashboardService:
    def __init__(self, repository: DashboardRepository):
        self.repository = repository

    async def get_metrics(self, window: str) -> MetricsResponse:
        metrics = await self.repository.get_metrics(window)
        return MetricsResponse(
            window=window,
            generated_at=datetime.utcnow().isoformat() + "Z",
            users=metrics["users"],
            referrals=metrics["referrals"],
            rewards=metrics["rewards"],
            fraud=metrics["fraud"],
            system=metrics["system"]
        )

    async def get_fraud_panel(self, page: int = 1, limit: int = 20) -> FraudPanelResponse:
        # Fallback to mock data if db is empty for UI to work smoothly
        events = await self.repository.get_fraud_events(limit)
        return FraudPanelResponse(
            events=[{
                "id": str(e.id),
                "user": {"id": str(e.user_id), "username": f"user_{str(e.user_id)[:5]}"},
                "reason": str(e.reason),
                "severity": e.severity,
                "severity_label": "HIGH" if e.severity == 3 else "MEDIUM",
                "referral_attempt": {"attempted_referrer": {"id": "mock", "username": "mock_referrer"}, "timestamp": e.created_at.isoformat() + "Z"},
                "metadata": e.metadata,
                "reviewed": e.reviewed,
                "created_at": e.created_at.isoformat() + "Z"
            } for e in events] if events else [],
            pagination={"page": page, "limit": limit, "total": len(events)},
            summary={"total_unreviewed": 0, "high_severity_unreviewed": 0}
        )

    async def get_activity_feed(self, limit: int = 50) -> ActivityFeedResponse:
        events = await self.repository.get_activity_feed(limit)
        return ActivityFeedResponse(
            events=[{
                "id": str(e.id),
                "event_type": str(e.event_type),
                "label": "System Event",
                "actor": {"id": "system", "username": "System"},
                "target": None,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() + "Z"
            } for e in events] if events else []
        )

    async def get_graph(self, user_id: str, depth: int) -> GraphResponse:
        return GraphResponse(
            root_user_id=user_id,
            depth=depth,
            nodes=[
                {"id": user_id, "username": "Root", "referral_count": 0, "is_root": True, "depth_from_root": 0}
            ],
            edges=[],
            stats={"total_nodes": 1, "total_edges": 0, "max_depth_found": 0}
        )

async def get_dashboard_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session)
) -> AsyncIterator[DashboardService]:
    repo = DashboardRepository(
        session=session,
        redis=request.app.state.redis,
        neo4j_driver=request.app.state.neo4j_driver,
        settings=request.app.state.settings,
    )
    yield DashboardService(repo)
