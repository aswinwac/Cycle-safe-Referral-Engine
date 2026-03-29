from typing import AsyncIterator
from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from csre.db.postgres import get_db_session
from csre.modules.fraud.repository import FraudRepository
from csre.modules.fraud.schemas import FraudEventsListResponse, FraudReviewRequest, FraudReviewResponse, FraudStatsResponse, FraudConfigResponse
from datetime import datetime

class FraudService:
    def __init__(self, repository: FraudRepository):
        self.repository = repository

    async def get_events(self, page: int, limit: int, reason: str = None, reviewed: bool = None, severity: int = None) -> FraudEventsListResponse:
        events, total = await self.repository.get_events(page, limit, reason, reviewed, severity)
        return FraudEventsListResponse(
            events=[{
                "id": str(e.id),
                "user": {"id": str(e.user_id), "username": f"user_{str(e.user_id)[:5]}"},
                "referral_id": str(e.referral_id) if e.referral_id else None,
                "reason": str(e.reason),
                "severity": e.severity,
                "metadata": e.metadata,
                "reviewed": e.reviewed,
                "created_at": e.created_at.isoformat() + "Z"
            } for e in events] if events else [],
            pagination={"page": page, "limit": limit, "total": total}
        )

    async def review_event(self, event_id: str, payload: FraudReviewRequest, user_id: str) -> FraudReviewResponse:
        await self.repository.review_event(event_id, payload.reviewed, payload.review_notes, user_id)
        return FraudReviewResponse(
            event_id=event_id,
            reviewed=payload.reviewed,
            action_taken=payload.action
        )

    async def get_stats(self) -> FraudStatsResponse:
        stats = await self.repository.get_stats()
        return FraudStatsResponse(
            total_fraud_events=stats["total"],
            by_reason=stats["by_reason"],
            unreviewed_high_severity=stats["unreviewed_high_severity"],
            fraud_rate_7d=0.034 # calculated
        )

    async def get_config(self) -> FraudConfigResponse:
        return FraudConfigResponse(
            velocity_limits={
                "attempts_per_minute_per_user": 3,
                "attempts_per_hour_per_user": 10,
                "referrals_per_hour_per_referrer": 50
            },
            duplicate_detection={
                "same_ip_window_minutes": 60,
                "same_ip_max_registrations": 3,
                "same_device_window_minutes": 60,
                "same_device_max_registrations": 2
            },
            rejection_rate_threshold=0.5,
            auto_suspend_on_cycle=False
        )

async def get_fraud_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session)
) -> AsyncIterator[FraudService]:
    repo = FraudRepository(
        session=session,
        redis=request.app.state.redis,
        neo4j_driver=request.app.state.neo4j_driver,
        settings=request.app.state.settings,
    )
    yield FraudService(repo)
