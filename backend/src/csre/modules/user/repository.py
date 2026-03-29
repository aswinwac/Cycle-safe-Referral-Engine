import json
from decimal import Decimal
from typing import Any

from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from csre.core.config import Settings
from csre.db.models import (
    ActivityEventRecord,
    FraudEventRecord,
    GraphSyncQueueRecord,
    ReferralRecord,
    RewardRecord,
    UserRecord,
)
from csre.db.base import utcnow


class UserRepository:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis | None,
        neo4j_driver: AsyncDriver | None,
        settings: Settings,
    ) -> None:
        self.session = session
        self.redis = redis
        self.neo4j_driver = neo4j_driver
        self.settings = settings

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        return await self._scalar(select(UserRecord).where(UserRecord.email == email))

    async def get_user_by_username(self, username: str) -> UserRecord | None:
        return await self._scalar(select(UserRecord).where(UserRecord.username == username))

    async def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return await self._scalar(select(UserRecord).where(UserRecord.id == user_id))

    async def get_user_by_referral_code(self, referral_code: str) -> UserRecord | None:
        return await self._scalar(
            select(UserRecord).where(UserRecord.referral_code == referral_code)
        )

    async def referral_code_exists(self, referral_code: str) -> bool:
        result = await self.session.execute(
            select(func.count(UserRecord.id)).where(UserRecord.referral_code == referral_code)
        )
        return bool(result.scalar_one())

    async def has_duplicate_ip(self, ip_address: str | None) -> bool:
        if not ip_address:
            return False
        result = await self.session.execute(
            select(func.count(UserRecord.id)).where(UserRecord.ip_address == ip_address)
        )
        return bool(result.scalar_one())

    async def has_duplicate_device(self, device_hash: str | None) -> bool:
        if not device_hash:
            return False
        result = await self.session.execute(
            select(func.count(UserRecord.id)).where(UserRecord.device_hash == device_hash)
        )
        return bool(result.scalar_one())

    async def create_user(self, user: UserRecord) -> UserRecord:
        self.session.add(user)
        await self.session.flush()
        return user

    async def create_referral(
        self,
        *,
        referrer_id: str,
        referred_id: str,
        ip_address: str | None,
        device_hash: str | None,
    ) -> ReferralRecord:
        referral = ReferralRecord(
            referrer_id=referrer_id,
            referred_id=referred_id,
            status="VALID",
            depth=1,
            ip_address=ip_address,
            device_hash=device_hash,
            resolved_at=utcnow(),
        )
        self.session.add(referral)
        await self.session.flush()
        return referral

    async def create_fraud_signal(
        self,
        *,
        user_id: str,
        reason: str,
        metadata: dict[str, Any],
        severity: int = 1,
        referral_id: str | None = None,
    ) -> FraudEventRecord:
        event = FraudEventRecord(
            user_id=user_id,
            referral_id=referral_id,
            reason=reason,
            event_metadata=metadata,
            severity=severity,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def create_activity_event(
        self,
        *,
        event_type: str,
        actor_id: str | None,
        target_id: str | None,
        payload: dict[str, Any],
    ) -> ActivityEventRecord:
        event = ActivityEventRecord(
            event_type=event_type,
            actor_id=actor_id,
            target_id=target_id,
            payload=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def queue_graph_sync_event(self, *, event_type: str, payload: dict[str, Any]) -> None:
        serialized_payload = json.dumps(payload, default=str)
        self.session.add(GraphSyncQueueRecord(event_type=event_type, payload=serialized_payload))
        if self.redis is None:
            return
        try:
            await self.redis.rpush("graph_sync:users", serialized_payload)
        except Exception:
            return

    async def resolve_referral_code(self, referral_code: str) -> UserRecord | None:
        cache_key = self._referral_code_cache_key(referral_code)
        cached_user_id: str | None = None

        if self.redis is not None:
            try:
                cached_user_id = await self.redis.get(cache_key)
            except Exception:
                cached_user_id = None

        user: UserRecord | None = None
        if cached_user_id:
            user = await self.get_user_by_id(cached_user_id)
            if user is None or user.status == "DEACTIVATED":
                if self.redis is not None:
                    try:
                        await self.redis.delete(cache_key)
                    except Exception:
                        pass
                user = None
            elif self.redis is not None:
                try:
                    await self.redis.expire(cache_key, 3600)
                except Exception:
                    pass

        if user is None:
            user = await self.get_user_by_referral_code(referral_code)
            if user and user.status != "DEACTIVATED":
                await self.cache_referral_code_lookup(referral_code, user.id)
            elif user and user.status == "DEACTIVATED":
                return None

        return user

    async def cache_referral_code_lookup(self, referral_code: str, user_id: str) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(self._referral_code_cache_key(referral_code), user_id, ex=3600)
        except Exception:
            return

    async def get_cached_profile(self, user_id: str) -> str | None:
        if self.redis is None:
            return None
        try:
            return await self.redis.get(self._profile_cache_key(user_id))
        except Exception:
            return None

    async def cache_profile(self, user_id: str, payload: str) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(self._profile_cache_key(user_id), payload, ex=300)
        except Exception:
            return

    async def invalidate_profile_cache(self, user_id: str | None) -> None:
        if self.redis is None or user_id is None:
            return
        try:
            await self.redis.delete(self._profile_cache_key(user_id))
        except Exception:
            return

    async def store_refresh_token(self, token_id: str, user_id: str, ttl_seconds: int) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(self._refresh_token_key(token_id), user_id, ex=ttl_seconds)
        except Exception:
            return

    async def get_refresh_token_subject(self, token_id: str) -> str | None:
        if self.redis is None:
            return None
        try:
            return await self.redis.get(self._refresh_token_key(token_id))
        except Exception:
            return None

    async def revoke_refresh_token(self, token_id: str) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.delete(self._refresh_token_key(token_id))
        except Exception:
            return

    async def create_graph_user(self, user: UserRecord) -> None:
        if self.neo4j_driver is None:
            return
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                """
                MERGE (u:User {id: $user_id})
                SET u.username = $username,
                    u.created_at = datetime($created_at),
                    u.status = $status
                """,
                user_id=user.id,
                username=user.username,
                created_at=user.created_at.isoformat(),
                status=user.status,
            )
            await result.consume()

    async def create_graph_referral_edge(self, referral: ReferralRecord) -> None:
        if self.neo4j_driver is None:
            return
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                """
                MATCH (child:User {id: $child_id})
                MATCH (parent:User {id: $parent_id})
                MERGE (child)-[r:REFERRED {referral_id: $referral_id}]->(parent)
                SET r.created_at = datetime($created_at),
                    r.depth = $depth
                """,
                child_id=referral.referred_id,
                parent_id=referral.referrer_id,
                referral_id=referral.id,
                created_at=referral.created_at.isoformat(),
                depth=referral.depth,
            )
            await result.consume()

    async def delete_graph_user(self, user_id: str) -> None:
        if self.neo4j_driver is None:
            return
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                "MATCH (u:User {id: $user_id}) DETACH DELETE u",
                user_id=user_id,
            )
            await result.consume()

    async def get_profile_snapshot(self, user_id: str) -> dict[str, Any] | None:
        referrer = aliased(UserRecord)
        total_referrals = (
            select(func.count(ReferralRecord.id))
            .where(ReferralRecord.referrer_id == user_id)
            .scalar_subquery()
        )
        valid_referrals = (
            select(func.count(ReferralRecord.id))
            .where(
                and_(
                    ReferralRecord.referrer_id == user_id,
                    ReferralRecord.status == "VALID",
                )
            )
            .scalar_subquery()
        )
        fraud_referrals = (
            select(func.count(ReferralRecord.id))
            .where(
                and_(
                    ReferralRecord.referrer_id == user_id,
                    ReferralRecord.status == "FRAUD",
                )
            )
            .scalar_subquery()
        )
        total_rewards = (
            select(func.coalesce(func.sum(RewardRecord.amount), Decimal("0")))
            .where(
                and_(
                    RewardRecord.recipient_id == user_id,
                    or_(RewardRecord.status == "ISSUED", RewardRecord.issued_at.is_not(None)),
                )
            )
            .scalar_subquery()
        )

        statement = (
            select(
                UserRecord.id,
                UserRecord.username,
                UserRecord.referral_code,
                UserRecord.status,
                UserRecord.created_at,
                referrer.id.label("referrer_id"),
                referrer.username.label("referrer_username"),
                total_referrals.label("total_referrals"),
                valid_referrals.label("valid_referrals"),
                fraud_referrals.label("fraud_referrals"),
                total_rewards.label("total_rewards_earned"),
            )
            .outerjoin(referrer, referrer.id == UserRecord.referrer_id)
            .where(UserRecord.id == user_id)
        )

        result = await self.session.execute(statement)
        row = result.mappings().one_or_none()
        return dict(row) if row else None

    async def get_referral_tree_rows(self, user_id: str, depth: int) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                """
                WITH RECURSIVE referral_tree AS (
                    SELECT id, username, referrer_id, 0 AS level
                    FROM users
                    WHERE id = :root_id
                    UNION ALL
                    SELECT child.id, child.username, child.referrer_id, referral_tree.level + 1
                    FROM users AS child
                    JOIN referral_tree ON child.referrer_id = referral_tree.id
                    WHERE referral_tree.level < :depth
                )
                SELECT id, username, referrer_id, level
                FROM referral_tree
                ORDER BY level ASC, username ASC
                """
            ),
            {"root_id": user_id, "depth": depth},
        )
        return [dict(row) for row in result.mappings().all()]

    async def _scalar(self, statement: Select[tuple[UserRecord]]) -> UserRecord | None:
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def check_path_exists(self, from_id: str, to_id: str, max_depth: int = 50) -> bool:
        """Check if there is a path from `from_id` to `to_id` following REFERRED edges.
        Returns True if such a path exists (indicating a cycle if we are adding edge from to_id to from_id).
        """
        if self.neo4j_driver is None:
            return False
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                """
                MATCH (start:User {id: $from_id})
                MATCH (end:User {id: $to_id})
                CALL apoc.path.expandConfig(start, {
                    relationshipFilter: 'REFERRED>',
                    minLevel: 1,
                    maxLevel: $max_depth,
                    terminatorNodes: [end]
                }) YIELD path
                RETURN COUNT(path) > 0 AS path_exists
                """,
                from_id=from_id,
                to_id=to_id,
                max_depth=max_depth,
            )
            record = await result.single()
            return record["path_exists"] if record else False

    async def get_all_ancestor_ids(self, user_id: str) -> set[str]:
        """Get all ancestor IDs of a user (following REFERRED edges upward)."""
        if self.neo4j_driver is None:
            return set()
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                """
                MATCH (start:User {id: $user_id})-[:REFERRED*1..]->(ancestor:User)
                RETURN COLLECT(ancestor.id) AS ancestor_ids
                """,
                user_id=user_id,
            )
            record = await result.single()
            if record and record["ancestor_ids"] is not None:
                return set(record["ancestor_ids"])
            return set()

    async def get_all_descendant_ids(self, user_id: str) -> set[str]:
        """Get all descendant IDs of a user (following REFERRED edges downward)."""
        if self.neo4j_driver is None:
            return set()
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                """
                MATCH (start:User {id: $user_id})<-[:REFERRED*1..]-(descendant:User)
                RETURN COLLECT(descendant.id) AS descendant_ids
                """,
                user_id=user_id,
            )
            record = await result.single()
            if record and record["descendant_ids"] is not None:
                return set(record["descendant_ids"])
            return set()

    @staticmethod
    def _profile_cache_key(user_id: str) -> str:
        return f"user:profile:{user_id}"

    @staticmethod
    def _referral_code_cache_key(referral_code: str) -> str:
        return f"user:code:{referral_code}"

    @staticmethod
    def _refresh_token_key(token_id: str) -> str:
        return f"auth:refresh:{token_id}"
