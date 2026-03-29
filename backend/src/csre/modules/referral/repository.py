import hashlib
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from csre.core.config import Settings
from csre.db.base import utcnow
from csre.db.models import ReferralRecord, UserRecord


class ReferralRepository:
    """Persistence and graph/cache helpers for referral claims and queries."""

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

    @property
    def _max_graph_depth(self) -> int:
        return self.settings.referral_graph_max_depth

    async def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return await self.session.get(UserRecord, user_id)

    async def get_referrer_id(self, user_id: str) -> str | None:
        user = await self.session.get(UserRecord, user_id)
        return user.referrer_id if user else None

    async def referrer_has_ancestor_in_cache(self, referrer_id: str, candidate_ancestor_id: str) -> bool:
        if self.redis is None:
            return False
        try:
            return bool(
                await self.redis.sismember(self._ancestors_key(referrer_id), candidate_ancestor_id)
            )
        except Exception:
            return False

    async def warm_ancestor_cache(self, referrer_id: str, ancestor_ids: set[str], extra_id: str | None) -> None:
        if self.redis is None:
            return
        if not ancestor_ids and extra_id is None:
            return
        key = self._ancestors_key(referrer_id)
        try:
            if ancestor_ids:
                await self.redis.sadd(key, *ancestor_ids)
            if extra_id:
                await self.redis.sadd(key, extra_id)
            await self.redis.expire(key, self.settings.referral_ancestors_cache_ttl_seconds)
        except Exception:
            return

    async def invalidate_ancestor_caches(self, user_ids: Iterable[str]) -> None:
        if self.redis is None:
            return
        keys = [self._ancestors_key(uid) for uid in user_ids]
        try:
            if keys:
                await self.redis.delete(*keys)
        except Exception:
            return

    async def try_redis_claim_lock(self, new_user_id: str) -> bool:
        """Redis SET NX lock. False = not acquired (held by peer or error)."""
        if self.redis is None:
            return False
        try:
            ok = await self.redis.set(
                self._lock_key(new_user_id),
                "1",
                nx=True,
                px=self.settings.referral_lock_ttl_ms,
            )
            return bool(ok)
        except Exception:
            return False

    @staticmethod
    def _advisory_lock_keys(user_id: str) -> tuple[int, int]:
        digest = hashlib.sha256(f"csre:referral_claim:{user_id}".encode()).digest()
        k1 = int.from_bytes(digest[:4], "big", signed=False) & 0x7FFFFFFF
        k2 = int.from_bytes(digest[4:8], "big", signed=False) & 0x7FFFFFFF
        return k1, k2

    async def pg_try_advisory_lock_claim(self, user_id: str) -> bool:
        k1, k2 = self._advisory_lock_keys(user_id)
        result = await self.session.execute(
            text("SELECT pg_try_advisory_lock(:k1, :k2)"),
            {"k1": k1, "k2": k2},
        )
        return bool(result.scalar_one())

    async def pg_advisory_unlock_claim(self, user_id: str) -> None:
        k1, k2 = self._advisory_lock_keys(user_id)
        await self.session.execute(
            text("SELECT pg_advisory_unlock(:k1, :k2)"),
            {"k1": k1, "k2": k2},
        )

    async def increment_referral_velocity(self, user_id: str) -> int:
        """Sliding minute bucket; returns attempt count this minute. 0 if Redis unavailable (caller fail-open)."""
        if self.redis is None:
            return 0
        minute = int(time.time() // 60)
        key = f"referral_velocity:{user_id}:{minute}"
        try:
            count = await self.redis.incr(key)
            if count == 1:
                await self.redis.expire(key, self.settings.referral_velocity_window_seconds)
            return int(count)
        except Exception:
            return 0

    async def depth_for_new_referral_edge(self, referrer_id: str) -> int:
        """Depth of the new edge: 1 + depth of referrer's incoming VALID referral, else 1."""
        result = await self.session.execute(
            select(ReferralRecord.depth)
            .where(
                ReferralRecord.referred_id == referrer_id,
                ReferralRecord.status == "VALID",
            )
            .limit(1)
        )
        parent_depth = result.scalar_one_or_none()
        return int(parent_depth or 0) + 1

    async def release_claim_lock(self, new_user_id: str) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.delete(self._lock_key(new_user_id))
        except Exception:
            return

    async def neo4j_cycle_would_form(self, referrer_id: str, new_user_id: str) -> bool:
        """True if a path referrer -[:REFERRED*]-> new_user already exists (adding new_user->referrer would cycle)."""
        if self.neo4j_driver is None:
            return False
        md = self._max_graph_depth
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                f"""
                MATCH (r:User {{id: $referrer_id}}), (n:User {{id: $new_user_id}})
                OPTIONAL MATCH p = (r)-[:REFERRED*1..{md}]->(n)
                RETURN p IS NOT NULL AS cycle_exists
                """,
                referrer_id=referrer_id,
                new_user_id=new_user_id,
            )
            record = await result.single()
            return bool(record and record["cycle_exists"])

    async def neo4j_ancestor_ids(self, user_id: str) -> set[str]:
        if self.neo4j_driver is None:
            return set()
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                f"""
                MATCH (start:User {{id: $user_id}})-[:REFERRED*1..{self._max_graph_depth}]->(ancestor:User)
                RETURN COLLECT(ancestor.id) AS ancestor_ids
                """,
                user_id=user_id,
            )
            record = await result.single()
            if record and record["ancestor_ids"]:
                return set(record["ancestor_ids"])
            return set()

    async def neo4j_descendant_ids(self, user_id: str) -> set[str]:
        if self.neo4j_driver is None:
            return set()
        async with self.neo4j_driver.session(database=self.settings.neo4j_database) as session:
            result = await session.run(
                f"""
                MATCH (start:User {{id: $user_id}})<-[:REFERRED*1..{self._max_graph_depth}]-(d:User)
                RETURN COLLECT(d.id) AS descendant_ids
                """,
                user_id=user_id,
            )
            record = await result.single()
            if record and record["descendant_ids"]:
                return set(record["descendant_ids"])
            return set()

    async def create_graph_edge(
        self,
        *,
        referral_id: str,
        child_id: str,
        parent_id: str,
        created_at: datetime,
        depth: int,
    ) -> None:
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
                child_id=child_id,
                parent_id=parent_id,
                referral_id=referral_id,
                created_at=created_at.isoformat(),
                depth=depth,
            )
            await result.consume()

    async def insert_referral_pending(
        self,
        *,
        referral_id: str,
        referrer_id: str,
        referred_id: str,
        depth: int,
        ip_address: str | None,
        device_hash: str | None,
    ) -> ReferralRecord:
        referral = ReferralRecord(
            id=referral_id,
            referrer_id=referrer_id,
            referred_id=referred_id,
            status="PENDING",
            depth=depth,
            ip_address=ip_address,
            device_hash=device_hash,
        )
        self.session.add(referral)
        await self.session.flush()
        return referral

    async def set_user_referrer(self, user_id: str, referrer_id: str) -> None:
        user = await self.session.get(UserRecord, user_id)
        if user is None:
            return
        user.referrer_id = referrer_id
        user.updated_at = utcnow()
        await self.session.flush()

    async def mark_referral_valid(self, referral_id: str) -> None:
        referral = await self.session.get(ReferralRecord, referral_id)
        if referral is None:
            return
        referral.status = "VALID"
        referral.resolved_at = utcnow()
        await self.session.flush()

    async def compensate_failed_graph_write(self, referral_id: str, referred_user_id: str) -> None:
        referral = await self.session.get(ReferralRecord, referral_id)
        if referral is not None:
            referral.status = "REJECTED"
            referral.resolved_at = utcnow()
        user = await self.session.get(UserRecord, referred_user_id)
        if user is not None:
            user.referrer_id = None
            user.updated_at = utcnow()
        await self.session.flush()

    async def get_referral_detail_row(self, referral_id: str) -> dict[str, Any] | None:
        ref = aliased(UserRecord)
        rfd = aliased(UserRecord)
        stmt = (
            select(
                ReferralRecord.id,
                ReferralRecord.referrer_id,
                ReferralRecord.referred_id,
                ReferralRecord.status,
                ReferralRecord.depth,
                ReferralRecord.ip_address,
                ReferralRecord.device_hash,
                ReferralRecord.fraud_reason,
                ReferralRecord.fraud_metadata,
                ReferralRecord.created_at,
                ReferralRecord.resolved_at,
                ref.username.label("referrer_username"),
                rfd.username.label("referred_username"),
            )
            .join(ref, ref.id == ReferralRecord.referrer_id)
            .join(rfd, rfd.id == ReferralRecord.referred_id)
            .where(ReferralRecord.id == referral_id)
        )
        result = await self.session.execute(stmt)
        row = result.mappings().one_or_none()
        return dict(row) if row else None

    async def update_referral_status_admin(
        self,
        *,
        referral_id: str,
        status: str,
        fraud_reason: str | None,
        fraud_metadata: dict[str, Any] | None,
    ) -> ReferralRecord | None:
        referral = await self.session.get(ReferralRecord, referral_id)
        if referral is None:
            return None
        referral.status = status
        if fraud_reason is not None:
            referral.fraud_reason = fraud_reason
        if fraud_metadata is not None:
            referral.fraud_metadata = fraud_metadata
        if status in ("VALID", "REJECTED", "FRAUD"):
            referral.resolved_at = utcnow()
        await self.session.flush()
        return referral

    async def list_referrals_for_user(
        self,
        *,
        user_id: str,
        role: str,
        status_filter: str | None,
        page: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        page = max(page, 1)
        limit = min(max(limit, 1), 100)
        offset = (page - 1) * limit

        conditions = []
        if role == "referred":
            conditions.append(ReferralRecord.referred_id == user_id)
        else:
            conditions.append(ReferralRecord.referrer_id == user_id)

        if status_filter:
            conditions.append(ReferralRecord.status == status_filter)

        base_where = and_(*conditions) if conditions else True

        count_stmt = select(func.count()).select_from(ReferralRecord).where(base_where)
        total = int((await self.session.execute(count_stmt)).scalar_one())

        ref = aliased(UserRecord)
        rfd = aliased(UserRecord)
        stmt = (
            select(
                ReferralRecord.id,
                ReferralRecord.referrer_id,
                ReferralRecord.referred_id,
                ReferralRecord.status,
                ReferralRecord.depth,
                ReferralRecord.ip_address,
                ReferralRecord.device_hash,
                ReferralRecord.fraud_reason,
                ReferralRecord.fraud_metadata,
                ReferralRecord.created_at,
                ReferralRecord.resolved_at,
                ref.username.label("referrer_username"),
                rfd.username.label("referred_username"),
            )
            .join(ref, ref.id == ReferralRecord.referrer_id)
            .join(rfd, rfd.id == ReferralRecord.referred_id)
            .where(base_where)
            .order_by(ReferralRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = [dict(r) for r in result.mappings().all()]
        return rows, total

    @staticmethod
    def _ancestors_key(user_id: str) -> str:
        return f"ancestors:{user_id}"

    @staticmethod
    def _lock_key(user_id: str) -> str:
        return f"referral_lock:{user_id}"
