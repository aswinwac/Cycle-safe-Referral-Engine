from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Any

class FraudRepository:
    def __init__(self, session: AsyncSession, redis: Any, neo4j_driver: Any, settings: Any):
        self.session = session
        self.redis = redis
        self.neo4j_driver = neo4j_driver
        self.settings = settings

    async def get_events(self, page: int, limit: int, reason: str = None, reviewed: bool = None, severity: int = None):
        offset = (page - 1) * limit
        conditions = []
        params = {"limit": limit, "offset": offset}
        if reason:
            conditions.append("reason = :reason")
            params["reason"] = reason
        if reviewed is not None:
            conditions.append("reviewed = :reviewed")
            params["reviewed"] = reviewed
        if severity:
            conditions.append("severity = :severity")
            params["severity"] = severity
            
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"SELECT id, user_id, referral_id, reason, severity, metadata, reviewed, created_at FROM fraud_events {where_clause} ORDER BY created_at DESC LIMIT :limit OFFSET :offset")
        count_query = text(f"SELECT COUNT(*) FROM fraud_events {where_clause}")
        
        res = await self.session.execute(query, params)
        total_res = await self.session.execute(count_query, params)
        
        return res.fetchall(), total_res.scalar()

    async def review_event(self, event_id: str, reviewed: bool, review_notes: str, user_id: str):
        query = text("UPDATE fraud_events SET reviewed = :reviewed, review_notes = :notes, reviewed_by = :user_id, reviewed_at = NOW() WHERE id = :id RETURNING id")
        res = await self.session.execute(query, {"reviewed": reviewed, "notes": review_notes, "user_id": user_id, "id": event_id})
        return res.scalar()

    async def get_stats(self):
        total_q = text("SELECT COUNT(*) FROM fraud_events")
        reason_q = text("SELECT reason, COUNT(*) FROM fraud_events GROUP BY reason")
        urg_q = text("SELECT COUNT(*) FROM fraud_events WHERE reviewed = FALSE AND severity = 3")
        
        total = await self.session.execute(total_q)
        reasons = await self.session.execute(reason_q)
        urg = await self.session.execute(urg_q)
        
        return {
            "total": total.scalar(),
            "by_reason": {r[0]: r[1] for r in reasons.fetchall()},
            "unreviewed_high_severity": urg.scalar()
        }
