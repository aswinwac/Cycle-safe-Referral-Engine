from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Any
import json

class RewardRepository:
    def __init__(self, session: AsyncSession, redis: Any, neo4j_driver: Any, settings: Any):
        self.session = session
        self.redis = redis
        self.neo4j_driver = neo4j_driver
        self.settings = settings

    async def get_ledger(self, user_id: str, status: str, page: int, limit: int):
        offset = (page - 1) * limit
        
        conds = ["recipient_id = :user_id"]
        params = {"user_id": user_id, "limit": limit, "offset": offset}
        if status:
            conds.append("status = :status")
            params["status"] = status
            
        where = " AND ".join(conds)
        
        # summary stats
        earned_q = text("SELECT COALESCE(SUM(amount), 0) FROM rewards WHERE recipient_id = :user_id AND status = 'ISSUED'")
        pending_q = text("SELECT COALESCE(SUM(amount), 0) FROM rewards WHERE recipient_id = :user_id AND status = 'PENDING'")
        earned = await self.session.execute(earned_q, {"user_id": user_id})
        pending = await self.session.execute(pending_q, {"user_id": user_id})
        
        # rows
        query = text(f"SELECT id, referral_id, trigger_user_id, level, reward_type, amount, status, issued_at FROM rewards WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset")
        count_q = text(f"SELECT COUNT(*) FROM rewards WHERE {where}")
        
        res = await self.session.execute(query, params)
        total = await self.session.execute(count_q, params)
        
        return res.fetchall(), total.scalar(), earned.scalar(), pending.scalar()

    async def get_summary(self):
        query = text("SELECT level, COUNT(*), SUM(amount) FROM rewards WHERE status = 'ISSUED' GROUP BY level")
        res = await self.session.execute(query)
        levels = res.fetchall()
        
        tot_q = text("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM rewards WHERE status = 'ISSUED'")
        tot_res = await self.session.execute(tot_q)
        tot = tot_res.fetchone()
        
        pen_q = text("SELECT COALESCE(SUM(amount), 0) FROM rewards WHERE status = 'PENDING'")
        pen_res = await self.session.execute(pen_q)
        
        return tot[0], tot[1], pen_res.scalar(), levels
