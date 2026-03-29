from collections.abc import AsyncIterator
from typing import Literal
from uuid import uuid4

from fastapi import Depends, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csre.core.exceptions import CSREException, ErrorCode
from csre.db.models import ReferralRecord
from csre.db.postgres import get_db_session
from csre.modules.referral.repository import ReferralRepository
from csre.modules.referral.schemas import (
    ReferralAdminReviewRequest,
    ReferralDetailResponse,
    ReferralGetResponse,
    ReferralResponse,
    ReferralUserRef,
    UserReferralsResponse,
)
from csre.modules.user.repository import UserRepository


class ReferralService:
    def __init__(self, user_repo: UserRepository, referral_repo: ReferralRepository) -> None:
        self.user_repo = user_repo
        self.referral_repo = referral_repo

    @property
    def _settings(self):
        return self.user_repo.settings

    async def _acquire_claim_lock(self, user_id: str) -> Literal["redis", "pg"]:
        if self.referral_repo.redis is not None:
            try:
                if await self.referral_repo.try_redis_claim_lock(user_id):
                    return "redis"
                raise CSREException(
                    ErrorCode.LOCK_TIMEOUT,
                    "Could not acquire referral lock; try again",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            except CSREException:
                raise
            except Exception:
                pass
        if await self.referral_repo.pg_try_advisory_lock_claim(user_id):
            return "pg"
        raise CSREException(
            ErrorCode.LOCK_TIMEOUT,
            "Could not acquire referral lock; try again",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    async def _release_claim_lock(self, user_id: str, lock_kind: Literal["redis", "pg"]) -> None:
        if lock_kind == "redis":
            await self.referral_repo.release_claim_lock(user_id)
        else:
            await self.referral_repo.pg_advisory_unlock_claim(user_id)

    async def _enforce_velocity(self, user_id: str) -> None:
        count = await self.referral_repo.increment_referral_velocity(user_id)
        if self.referral_repo.redis is None:
            return
        if count > self._settings.referral_velocity_max_attempts_per_minute:
            async with self.user_repo.session.begin():
                await self.user_repo.create_fraud_signal(
                    user_id=user_id,
                    reason="VELOCITY_EXCEEDED",
                    metadata={"window": "minute", "count": count},
                    severity=1,
                )
                await self.user_repo.create_activity_event(
                    event_type="REFERRAL_REJECTED",
                    actor_id=user_id,
                    target_id=user_id,
                    payload={"reason": "VELOCITY_EXCEEDED", "count": count},
                )
            raise CSREException(
                ErrorCode.VELOCITY_EXCEEDED,
                "Too many referral attempts. Try again later.",
                status.HTTP_429_TOO_MANY_REQUESTS,
                details={"retry_after_seconds": 60},
            )

    async def claim_referral(
        self,
        *,
        user_id: str,
        referral_code: str,
        ip_address: str | None,
        device_hash: str | None,
    ) -> ReferralResponse:
        await self._enforce_velocity(user_id)

        normalized_code = referral_code.strip().upper()

        referrer = await self.user_repo.resolve_referral_code(normalized_code)
        if referrer is None:
            raise CSREException(
                ErrorCode.INVALID_CODE,
                "Referral code not found or expired",
                status.HTTP_400_BAD_REQUEST,
            )
        if referrer.status == "DEACTIVATED":
            raise CSREException(
                ErrorCode.INVALID_CODE,
                "Referral code not found or expired",
                status.HTTP_400_BAD_REQUEST,
            )

        claimant = await self.referral_repo.get_user_by_id(user_id)
        if claimant is None:
            raise CSREException(
                ErrorCode.USER_NOT_FOUND,
                "User not found",
                status.HTTP_404_NOT_FOUND,
            )

        if claimant.status != "ACTIVE":
            raise CSREException(
                ErrorCode.FRAUD_BLOCKED,
                "Account cannot claim referrals",
                status.HTTP_403_FORBIDDEN,
            )

        if user_id == referrer.id:
            async with self.user_repo.session.begin():
                fraud = await self.user_repo.create_fraud_signal(
                    user_id=user_id,
                    reason="SELF_REFERRAL",
                    metadata={"referral_code": normalized_code},
                    severity=3,
                )
                await self.user_repo.create_activity_event(
                    event_type="REFERRAL_REJECTED",
                    actor_id=user_id,
                    target_id=referrer.id,
                    payload={"reason": "SELF_REFERRAL", "fraud_event_id": fraud.id},
                )
            raise CSREException(
                ErrorCode.SELF_REFERRAL,
                "You cannot use your own referral code",
                status.HTTP_400_BAD_REQUEST,
                details={"fraud_event_id": fraud.id},
            )

        if claimant.referrer_id is not None:
            async with self.user_repo.session.begin():
                await self.user_repo.create_activity_event(
                    event_type="REFERRAL_REJECTED",
                    actor_id=user_id,
                    target_id=referrer.id,
                    payload={"reason": "DUPLICATE_REFERRAL"},
                )
            raise CSREException(
                ErrorCode.DUPLICATE_REFERRAL,
                "User already has a referrer",
                status.HTTP_409_CONFLICT,
            )

        if self.referral_repo.neo4j_driver is None:
            raise CSREException(
                ErrorCode.GRAPH_WRITE_FAILED,
                "Referral graph is unavailable",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        lock_kind = await self._acquire_claim_lock(user_id)

        try:
            if await self.referral_repo.get_referrer_id(user_id) is not None:
                async with self.user_repo.session.begin():
                    await self.user_repo.create_activity_event(
                        event_type="REFERRAL_REJECTED",
                        actor_id=user_id,
                        target_id=referrer.id,
                        payload={"reason": "DUPLICATE_REFERRAL"},
                    )
                raise CSREException(
                    ErrorCode.DUPLICATE_REFERRAL,
                    "User already has a referrer",
                    status.HTTP_409_CONFLICT,
                )

            if await self.referral_repo.referrer_has_ancestor_in_cache(referrer.id, user_id):
                async with self.user_repo.session.begin():
                    fraud = await self.user_repo.create_fraud_signal(
                        user_id=user_id,
                        reason="CYCLE_DETECTED",
                        metadata={"attempted_referrer_id": referrer.id, "layer": "redis_cache"},
                        severity=3,
                    )
                    await self.user_repo.create_activity_event(
                        event_type="REFERRAL_REJECTED",
                        actor_id=user_id,
                        target_id=referrer.id,
                        payload={"reason": "CYCLE_DETECTED", "fraud_event_id": fraud.id},
                    )
                raise CSREException(
                    ErrorCode.CYCLE_DETECTED,
                    "This referral would create a cycle in the referral graph",
                    status.HTTP_409_CONFLICT,
                    details={
                        "fraud_event_id": fraud.id,
                        "marked_as": "FRAUD",
                    },
                )

            cycle_exists = await self.referral_repo.neo4j_cycle_would_form(referrer.id, user_id)
            if cycle_exists:
                ancestors = await self.referral_repo.neo4j_ancestor_ids(referrer.id)
                await self.referral_repo.warm_ancestor_cache(referrer.id, ancestors, user_id)
                async with self.user_repo.session.begin():
                    fraud = await self.user_repo.create_fraud_signal(
                        user_id=user_id,
                        reason="CYCLE_DETECTED",
                        metadata={"attempted_referrer_id": referrer.id, "layer": "neo4j"},
                        severity=3,
                    )
                    await self.user_repo.create_activity_event(
                        event_type="REFERRAL_REJECTED",
                        actor_id=user_id,
                        target_id=referrer.id,
                        payload={"reason": "CYCLE_DETECTED", "fraud_event_id": fraud.id},
                    )
                raise CSREException(
                    ErrorCode.CYCLE_DETECTED,
                    "This referral would create a cycle in the referral graph",
                    status.HTTP_409_CONFLICT,
                    details={
                        "fraud_event_id": fraud.id,
                        "marked_as": "FRAUD",
                    },
                )

            referral_id = str(uuid4())
            depth = await self.referral_repo.depth_for_new_referral_edge(referrer.id)

            try:
                async with self.user_repo.session.begin():
                    await self.referral_repo.insert_referral_pending(
                        referral_id=referral_id,
                        referrer_id=referrer.id,
                        referred_id=user_id,
                        depth=depth,
                        ip_address=ip_address,
                        device_hash=device_hash,
                    )
                    await self.referral_repo.set_user_referrer(user_id, referrer.id)
            except IntegrityError as exc:
                async with self.user_repo.session.begin():
                    await self.user_repo.create_activity_event(
                        event_type="REFERRAL_REJECTED",
                        actor_id=user_id,
                        target_id=referrer.id,
                        payload={"reason": "DUPLICATE_REFERRAL"},
                    )
                raise CSREException(
                    ErrorCode.DUPLICATE_REFERRAL,
                    "User already has a referrer",
                    status.HTTP_409_CONFLICT,
                ) from exc

            referral_row = await self.user_repo.session.get(ReferralRecord, referral_id)
            created_at = referral_row.created_at if referral_row else None
            if created_at is None:
                async with self.user_repo.session.begin():
                    await self.referral_repo.compensate_failed_graph_write(referral_id, user_id)
                raise CSREException(
                    ErrorCode.GRAPH_WRITE_FAILED,
                    "Referral record could not be loaded",
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            try:
                await self.referral_repo.create_graph_edge(
                    referral_id=referral_id,
                    child_id=user_id,
                    parent_id=referrer.id,
                    created_at=created_at,
                    depth=depth,
                )
            except Exception:
                async with self.user_repo.session.begin():
                    await self.referral_repo.compensate_failed_graph_write(referral_id, user_id)
                    await self.user_repo.create_activity_event(
                        event_type="REFERRAL_REJECTED",
                        actor_id=user_id,
                        target_id=referrer.id,
                        payload={"reason": "GRAPH_WRITE_FAILED", "referral_id": referral_id},
                    )
                raise CSREException(
                    ErrorCode.GRAPH_WRITE_FAILED,
                    "Failed to record referral in the graph",
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            async with self.user_repo.session.begin():
                await self.referral_repo.mark_referral_valid(referral_id)

            descendants = await self.referral_repo.neo4j_descendant_ids(user_id)
            await self.referral_repo.invalidate_ancestor_caches({user_id, *descendants})

            await self.user_repo.invalidate_profile_cache(user_id)
            await self.user_repo.invalidate_profile_cache(referrer.id)

            async with self.user_repo.session.begin():
                await self.user_repo.create_activity_event(
                    event_type="REFERRAL_CREATED",
                    actor_id=referrer.id,
                    target_id=user_id,
                    payload={"referral_id": referral_id, "status": "VALID"},
                )
        finally:
            await self._release_claim_lock(user_id, lock_kind)

        from csre.tasks.rewards import distribute_referral_rewards

        distribute_referral_rewards.delay(referral_id)

        detail = await self._get_referral_detail(referral_id)
        return ReferralResponse(
            referral=detail,
            rewards_triggered=True,
            reward_job_id=referral_id,
        )

    async def get_referral(self, referral_id: str) -> ReferralGetResponse:
        row = await self.referral_repo.get_referral_detail_row(referral_id)
        if row is None:
            raise CSREException(
                ErrorCode.REFERRAL_NOT_FOUND,
                "Referral not found",
                status.HTTP_404_NOT_FOUND,
            )
        return self._row_to_get_response(row)

    async def get_user_referrals(
        self,
        *,
        user_id: str,
        role: str,
        status: str | None,
        page: int,
        limit: int,
    ) -> UserReferralsResponse:
        if role not in ("referrer", "referred"):
            role = "referrer"

        rows, total = await self.referral_repo.list_referrals_for_user(
            user_id=user_id,
            role=role,
            status_filter=status,
            page=page,
            limit=limit,
        )
        referrals = [self._row_to_get_response(r) for r in rows]
        return UserReferralsResponse(
            referrals=referrals,
            pagination={
                "page": page,
                "limit": limit,
                "total": total,
                "has_next": page * limit < total,
            },
        )

    async def admin_review_referral(
        self,
        *,
        referral_id: str,
        payload: ReferralAdminReviewRequest,
    ) -> ReferralGetResponse:
        row = await self.referral_repo.get_referral_detail_row(referral_id)
        if row is None:
            raise CSREException(
                ErrorCode.REFERRAL_NOT_FOUND,
                "Referral not found",
                status.HTTP_404_NOT_FOUND,
            )
        meta = dict(row.get("fraud_metadata") or {})
        if payload.notes:
            meta["admin_notes"] = payload.notes
        async with self.user_repo.session.begin():
            await self.referral_repo.update_referral_status_admin(
                referral_id=referral_id,
                status=payload.status,
                fraud_reason=payload.fraud_reason,
                fraud_metadata=meta,
            )
            await self.user_repo.create_activity_event(
                event_type="REFERRAL_ADMIN_REVIEW",
                actor_id=None,
                target_id=row["referred_id"],
                payload={"referral_id": referral_id, "status": payload.status},
            )
        row2 = await self.referral_repo.get_referral_detail_row(referral_id)
        if row2 is None:
            raise CSREException(
                ErrorCode.REFERRAL_NOT_FOUND,
                "Referral not found",
                status.HTTP_404_NOT_FOUND,
            )
        return self._row_to_get_response(row2)

    async def _get_referral_detail(self, referral_id: str) -> ReferralDetailResponse:
        row = await self.referral_repo.get_referral_detail_row(referral_id)
        if row is None:
            raise CSREException(
                ErrorCode.REFERRAL_NOT_FOUND,
                "Referral not found",
                status.HTTP_404_NOT_FOUND,
            )
        return self._row_to_detail(row)

    @staticmethod
    def _row_to_detail(row: dict) -> ReferralDetailResponse:
        created = row["created_at"]
        resolved = row.get("resolved_at")
        return ReferralDetailResponse(
            id=row["id"],
            referrer_id=row["referrer_id"],
            referrer_username=row["referrer_username"],
            referred_id=row["referred_id"],
            referred_username=row["referred_username"],
            status=row["status"],
            depth=row["depth"],
            ip_address=row.get("ip_address"),
            device_hash=row.get("device_hash"),
            fraud_reason=row.get("fraud_reason"),
            fraud_metadata=row.get("fraud_metadata") or {},
            created_at=created.isoformat() if hasattr(created, "isoformat") else str(created),
            resolved_at=resolved.isoformat() if resolved and hasattr(resolved, "isoformat") else None,
        )

    @staticmethod
    def _row_to_get_response(row: dict) -> ReferralGetResponse:
        created = row["created_at"]
        resolved = row.get("resolved_at")
        return ReferralGetResponse(
            id=row["id"],
            referrer=ReferralUserRef(id=row["referrer_id"], username=row["referrer_username"]),
            referred=ReferralUserRef(id=row["referred_id"], username=row["referred_username"]),
            status=row["status"],
            depth=row["depth"],
            fraud_reason=row.get("fraud_reason"),
            fraud_metadata=row.get("fraud_metadata") or {},
            created_at=created.isoformat() if hasattr(created, "isoformat") else str(created),
            resolved_at=resolved.isoformat() if resolved and hasattr(resolved, "isoformat") else None,
        )


async def get_referral_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> AsyncIterator[ReferralService]:
    settings = request.app.state.settings
    user_repo = UserRepository(
        session=session,
        redis=request.app.state.redis,
        neo4j_driver=request.app.state.neo4j_driver,
        settings=settings,
    )
    referral_repo = ReferralRepository(
        session=session,
        redis=request.app.state.redis,
        neo4j_driver=request.app.state.neo4j_driver,
        settings=settings,
    )
    yield ReferralService(user_repo, referral_repo)
