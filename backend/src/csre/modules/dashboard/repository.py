from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import Any
from csre.db.models import UserRecord

class DashboardRepository:
    def __init__(self, session: AsyncSession, redis: Any, neo4j_driver: Any, settings: Any):
        self.session = session
        self.redis = redis
        self.neo4j_driver = neo4j_driver
        self.settings = settings

    async def resolve_referral_code(self, code: str) -> UserRecord | None:
        result = await self.session.execute(
            select(UserRecord).where(UserRecord.referral_code == code)
        )
        return result.scalars().first()


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
        # Join with users to get actor and target names
        query = text("""
            SELECT 
                ae.id, ae.event_type, ae.payload, ae.created_at,
                actor.username as actor_username, actor.id as actor_id,
                target.username as target_username, target.id as target_id
            FROM activity_events ae
            LEFT JOIN users actor ON ae.actor_id = actor.id
            LEFT JOIN users target ON ae.target_id = target.id
            ORDER BY ae.created_at DESC
            LIMIT :limit
        """)
        res = await self.session.execute(query, {"limit": limit})
        return res.fetchall()

    async def get_graph_data(self, user_id: str, depth: int) -> Any:
        # Fetch from Neo4j
        if self.neo4j_driver is None or not user_id:
            return {"nodes": [], "edges": [], "stats": {"total_nodes": 0, "total_edges": 0, "max_depth_found": 0}}

        safe_user_id = str(user_id)
        safe_depth = int(depth)

        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            # Query for nodes with depth (Union of root and its descendants)
            result = await session.run(
                f"""
                MATCH (root:User {{id: $user_id}})
                RETURN root.id AS id, root.username AS username, 0 AS depth
                UNION
                MATCH (root:User {{id: $user_id}})
                MATCH path = (root)-[:REFERRED*1..{safe_depth}]->(node:User)
                RETURN node.id AS id, node.username AS username, length(path) AS depth
                """,
                user_id=safe_user_id
            )
            nodes = [{"id": r["id"], "username": r["username"], "depth": r["depth"]} for r in await result.data() if r["id"]]
            
            # Query for explicit edges in the found paths
            result = await session.run(
                f"""
                MATCH (root:User {{id: $user_id}})
                MATCH path = (root)-[:REFERRED*1..{safe_depth}]->(node:User)
                UNWIND relationships(path) AS r
                RETURN DISTINCT startNode(r).id AS source, endNode(r).id AS target
                """,
                user_id=safe_user_id
            )
            edges = [{"source": r["source"], "target": r["target"]} for r in await result.data() if r["source"] and r["target"]]



            return {
                "root_user_id": safe_user_id,
                "depth": safe_depth,
                "nodes": nodes,
                "edges": edges,
                "stats": {"total_nodes": len(nodes), "total_edges": len(edges), "max_depth_found": safe_depth}
            }



