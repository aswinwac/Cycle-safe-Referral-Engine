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
        rows = await self.repository.get_activity_feed(limit)
        events = []
        for row in rows:
            # Determine label based on type
            label = "System Activity"
            if row.event_type == "USER_REGISTERED":
                label = "New User Joined" if not row.target_id else "Referral Registration"
            elif row.event_type == "FRAUD_FLAGGED":
                label = "Fraud Risk Detected"
            elif row.event_type == "REWARD_ISSUED":
                label = "Incentive Distributed"

            events.append({
                "id": str(row.id),
                "event_type": str(row.event_type),
                "label": label,
                "actor": {"id": str(row.actor_id), "username": row.actor_username or "Deleted User"} if row.actor_id else {"id": "system", "username": "System"},
                "target": {"id": str(row.target_id), "username": row.target_username or "Deleted User"} if row.target_id else None,
                "payload": row.payload,
                "created_at": row.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')
            })

        
        return ActivityFeedResponse(events=events)


    async def get_graph(self, user_id: str, depth: int) -> GraphResponse:
        # Resolve user_id: it could be a raw UUID or a referral code
        actual_user_id = str(user_id)
        # Simple check: if it has a hyphen and matches referral code pattern
        if "-" in user_id and len(user_id) <= 20:
             user = await self.repository.resolve_referral_code(user_id)
             if user:
                 actual_user_id = str(user.id)

        return await self.repository.get_graph_data(actual_user_id, depth)




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
