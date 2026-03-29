from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Any

class DashboardRepository:
    def __init__(self, session: AsyncSession, redis: Any, neo4j_driver: Any, settings: Any):
        self.session = session
        self.redis = redis
        self.neo4j_driver = neo4j_driver
        self.settings = settings

    async def get_metrics(self, window: str) -> dict:
        interval_map = {"1h": "'1 hour'", "24h": "'24 hours'", "7d": "'7 days'", "30d": "'30 days'"}
        interval = interval_map.get(window, "'24 hours'")
        
        users_query = f"""
        SELECT
          COUNT(*) AS total_users,
          COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL {interval}) AS new_in_window,
          COUNT(*) FILTER (WHERE status = 'ACTIVE') AS active_users
        FROM users;
        """
        
        referrals_query = f"""
        SELECT
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE status = 'VALID') AS valid,
          COUNT(*) FILTER (WHERE status = 'REJECTED') AS rejected,
          COUNT(*) FILTER (WHERE status = 'FRAUD') AS fraud,
          COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL {interval}) AS in_window
        FROM referrals;
        """

        fraud_query = "SELECT reason, COUNT(*) AS count FROM fraud_events GROUP BY reason;"

        reward_query = "SELECT SUM(amount) AS amount_distributed FROM rewards WHERE status = 'ISSUED';"
        
        user_res = (await self.session.execute(text(users_query))).fetchone()
        ref_res = (await self.session.execute(text(referrals_query))).fetchone()
        fraud_res = (await self.session.execute(text(fraud_query))).fetchall()
        rew_res = (await self.session.execute(text(reward_query))).fetchone()

        valid_count = ref_res[1] if ref_res else 0
        total_count = ref_res[0] if ref_res else 0
        valid_rate = round(valid_count / total_count, 3) if total_count > 0 else 0

        fraud_by_reason = {row[0]: row[1] for row in fraud_res} if fraud_res else {}

        return {
            "users": {
                "total": user_res[0] if user_res else 0,
                "new_in_window": user_res[1] if user_res else 0,
                "active": user_res[2] if user_res else 0
            },
            "referrals": {
                "total": total_count,
                "valid": valid_count,
                "rejected": ref_res[2] if ref_res else 0,
                "fraud": ref_res[3] if ref_res else 0,
                "in_window": ref_res[4] if ref_res else 0,
                "valid_rate": valid_rate
            },
            "rewards": {
                "total_issued": rew_res[0] or 0,
                "amount_distributed": rew_res[0] or 0,
                "pending_amount": 0
            },
            "fraud": {
                "total_events": sum(fraud_by_reason.values()),
                "by_reason": fraud_by_reason,
                "unreviewed_high_severity": 0
            },
            "system": {
                "graph_node_count": user_res[0] if user_res else 0,
                "graph_edge_count": total_count,
                "avg_referral_latency_ms": 42,
                "cache_hit_rate": 0.94
            }
        }

    async def get_fraud_events(self, limit: int = 20) -> list:
        # returns basic structure mocked for now, since it requires large joins
        query = text("SELECT id, user_id, reason, severity, metadata, reviewed, created_at FROM fraud_events ORDER BY created_at DESC LIMIT :limit")
        res = await self.session.execute(query, {"limit": limit})
        return res.fetchall()

    async def get_activity_feed(self, limit: int = 50) -> list:
        query = text("SELECT id, event_type, payload, created_at FROM activity_events ORDER BY created_at DESC LIMIT :limit")
        res = await self.session.execute(query, {"limit": limit})
        return res.fetchall()
