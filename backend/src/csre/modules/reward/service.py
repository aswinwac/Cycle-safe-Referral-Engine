from typing import AsyncIterator
from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from csre.db.postgres import get_db_session
from csre.modules.reward.repository import RewardRepository
from csre.modules.reward.schemas import RewardLedgerResponse, RewardConfigResponse, RewardSummaryResponse, RewardConfigPayload
import uuid

class RewardService:
    def __init__(self, repository: RewardRepository):
        self.repository = repository

    async def get_ledger(self, user_id: str, status: str, page: int, limit: int) -> RewardLedgerResponse:
        rows, total, earned, pending = await self.repository.get_ledger(user_id, status, page, limit)
        return RewardLedgerResponse(
            user_id=user_id,
            total_earned=float(earned),
            pending=float(pending),
            rewards=[{
                "id": str(r.id),
                "referral_id": str(r.referral_id),
                "trigger_user": {"id": str(r.trigger_user_id), "username": "trigger_user"},
                "level": r.level,
                "reward_type": r.reward_type,
                "amount": float(r.amount),
                "status": r.status,
                "issued_at": r.issued_at.isoformat() + "Z" if r.issued_at else None
            } for r in rows] if rows else [],
            pagination={"page": page, "limit": limit, "total": total}
        )

    async def get_summary(self) -> RewardSummaryResponse:
        total_count, total_amount, pending_amount, levels = await self.repository.get_summary()
        return RewardSummaryResponse(
            total_rewards_issued=total_count,
            total_amount_distributed=float(total_amount),
            pending_amount=float(pending_amount),
            by_level=[{
                "level": l[0], "count": l[1], "amount": float(l[2])
            } for l in levels] if levels else []
        )

    async def get_config(self) -> RewardConfigResponse:
        return RewardConfigResponse(
            active_config={
                "id": str(uuid.uuid4()),
                "name": "Standard Q1 2026",
                "max_depth": 3,
                "reward_type": "PERCENTAGE",
                "level_configs": [
                    {"level": 1, "value": 10.0},
                    {"level": 2, "value": 5.0},
                    {"level": 3, "value": 2.0}
                ],
                "is_active": True
            }
        )

async def get_reward_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session)
) -> AsyncIterator[RewardService]:
    repo = RewardRepository(
        session=session,
        redis=request.app.state.redis,
        neo4j_driver=request.app.state.neo4j_driver,
        settings=request.app.state.settings,
    )
    yield RewardService(repo)
