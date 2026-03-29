import re
import secrets
import string
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import Depends, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csre.core.exceptions import CSREException, ErrorCode
from csre.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_email,
    hash_password,
    normalize_email,
)
from csre.db.models import UserRecord
from csre.db.postgres import get_db_session
from csre.modules.user.repository import UserRepository
from csre.modules.user.schemas import (
    ReferralCodeLookupResponse,
    ReferralTreeNode,
    ReferralTreeResponse,
    RegistrationResponse,
    RegisteredUserResponse,
    TokenResponse,
    TokenRefreshRequest,
    UserProfileResponse,
    UserRegistrationRequest,
    UserStatsResponse,
)

BASE36_ALPHABET = string.digits + string.ascii_uppercase


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository
        self.settings = repository.settings

    async def register_user(self, payload: UserRegistrationRequest) -> RegistrationResponse:
        normalized_email = normalize_email(str(payload.email))
        normalized_username = payload.username.strip()
        ip_address = str(payload.ip_address) if payload.ip_address else None
        device_hash = payload.device_hash

        await self._ensure_unique_identity(normalized_email, normalized_username)

        referrer = None
        if payload.referral_code:
            referrer = await self.repository.resolve_referral_code(payload.referral_code)
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
            if referrer.email == normalized_email or referrer.username == normalized_username:
                raise CSREException(
                    ErrorCode.SELF_REFERRAL,
                    "You cannot use your own referral code",
                    status.HTTP_400_BAD_REQUEST,
                )

        duplicate_ip = await self.repository.has_duplicate_ip(ip_address)
        duplicate_device = await self.repository.has_duplicate_device(device_hash)
        referral_code = await self._generate_unique_referral_code(normalized_username)

        user = UserRecord(
            email=normalized_email,
            email_hash=hash_email(normalized_email),
            username=normalized_username,
            password_hash=hash_password(payload.password),
            referral_code=referral_code,
            referrer_id=referrer.id if referrer else None,
            status="ACTIVE",
            ip_address=ip_address,
            device_hash=device_hash,
        )

        referral = None
        graph_user_created = False

        try:
            async with self.repository.session.begin():
                user = await self.repository.create_user(user)
                if referrer is not None:
                    referral = await self.repository.create_referral(
                        referrer_id=referrer.id,
                        referred_id=user.id,
                        ip_address=ip_address,
                        device_hash=device_hash,
                    )

                try:
                    await self.repository.create_graph_user(user)
                    graph_user_created = True
                    if referral is not None:
                        await self.repository.create_graph_referral_edge(referral)
                except Exception as exc:
                    if self.settings.allow_async_graph_user_sync_on_failure:
                        await self.repository.queue_graph_sync_event(
                            event_type="USER_UPSERT",
                            payload={
                                "user_id": user.id,
                                "username": user.username,
                                "status": user.status,
                                "created_at": user.created_at.isoformat(),
                                "referral": (
                                    {
                                        "referral_id": referral.id,
                                        "referrer_id": referral.referrer_id,
                                        "referred_id": referral.referred_id,
                                        "created_at": referral.created_at.isoformat(),
                                        "depth": referral.depth,
                                    }
                                    if referral
                                    else None
                                ),
                            },
                        )
                    else:
                        raise CSREException(
                            ErrorCode.GRAPH_WRITE_FAILED,
                            "User graph node could not be created",
                            status.HTTP_500_INTERNAL_SERVER_ERROR,
                        ) from exc

                if duplicate_ip:
                    await self.repository.create_fraud_signal(
                        user_id=user.id,
                        reason="DUPLICATE_IP",
                        metadata={"ip_address": ip_address, "stage": "registration"},
                    )
                if duplicate_device:
                    await self.repository.create_fraud_signal(
                        user_id=user.id,
                        reason="DUPLICATE_DEVICE",
                        metadata={"device_hash": device_hash, "stage": "registration"},
                    )

                await self.repository.create_activity_event(
                    event_type="USER_REGISTERED",
                    actor_id=user.id,
                    target_id=user.id,
                    payload={"referrer_id": referrer.id if referrer else None},
                )
        except IntegrityError as exc:
            if graph_user_created:
                await self.repository.delete_graph_user(user.id)
            raise self._map_integrity_error(exc) from exc
        except CSREException:
            if graph_user_created:
                await self.repository.delete_graph_user(user.id)
            raise
        except Exception as exc:
            if graph_user_created:
                await self.repository.delete_graph_user(user.id)
            raise CSREException(
                ErrorCode.GRAPH_WRITE_FAILED,
                "Registration failed while syncing the user graph",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        await self.repository.cache_referral_code_lookup(user.referral_code, user.id)
        await self.repository.invalidate_profile_cache(user.id)
        if referrer is not None:
            await self.repository.invalidate_profile_cache(referrer.id)

        tokens = await self._issue_token_pair(user.id)
        return RegistrationResponse(
            user=RegisteredUserResponse(
                id=user.id,
                email=user.email,
                username=user.username,
                referral_code=user.referral_code,
                referrer_id=user.referrer_id,
                status=user.status,
                created_at=user.created_at,
            ),
            tokens=tokens,
        )

    async def refresh_tokens(self, payload: TokenRefreshRequest) -> TokenResponse:
        token_payload = decode_token(
            payload.refresh_token,
            self.settings,
            expected_type="refresh",
        )
        cached_subject = await self.repository.get_refresh_token_subject(token_payload.jti)
        if self.repository.redis is not None and cached_subject is None:
            raise CSREException(
                ErrorCode.INVALID_TOKEN,
                "Refresh token has been revoked",
                status.HTTP_401_UNAUTHORIZED,
            )
        if cached_subject is not None and cached_subject != token_payload.sub:
            raise CSREException(
                ErrorCode.INVALID_TOKEN,
                "Refresh token has been revoked",
                status.HTTP_401_UNAUTHORIZED,
            )

        user = await self.repository.get_user_by_id(token_payload.sub)
        if user is None:
            raise CSREException(
                ErrorCode.USER_NOT_FOUND,
                "User not found",
                status.HTTP_404_NOT_FOUND,
            )

        await self.repository.revoke_refresh_token(token_payload.jti)
        return await self._issue_token_pair(user.id)

    async def get_user_by_code(self, referral_code: str) -> ReferralCodeLookupResponse:
        normalized_code = referral_code.strip().upper()
        user = await self.repository.resolve_referral_code(normalized_code)
        if user is None:
            raise CSREException(
                ErrorCode.INVALID_CODE,
                "Referral code not found or expired",
                status.HTTP_404_NOT_FOUND,
            )

        return ReferralCodeLookupResponse(
            user_id=user.id,
            username=user.username,
            referral_code=user.referral_code,
        )

    async def get_profile(self, user_id: str) -> UserProfileResponse:
        cached_profile = await self.repository.get_cached_profile(user_id)
        if cached_profile:
            return UserProfileResponse.model_validate_json(cached_profile)

        snapshot = await self.repository.get_profile_snapshot(user_id)
        if snapshot is None:
            raise CSREException(
                ErrorCode.USER_NOT_FOUND,
                "User not found",
                status.HTTP_404_NOT_FOUND,
            )

        profile = UserProfileResponse(
            id=snapshot["id"],
            username=snapshot["username"],
            referral_code=snapshot["referral_code"],
            referrer=(
                {"id": snapshot["referrer_id"], "username": snapshot["referrer_username"]}
                if snapshot["referrer_id"]
                else None
            ),
            stats=UserStatsResponse(
                total_referrals=int(snapshot["total_referrals"] or 0),
                valid_referrals=int(snapshot["valid_referrals"] or 0),
                fraud_referrals=int(snapshot["fraud_referrals"] or 0),
                total_rewards_earned=snapshot["total_rewards_earned"] or 0,
            ),
            status=snapshot["status"],
            created_at=snapshot["created_at"],
        )
        await self.repository.cache_profile(user_id, profile.model_dump_json())
        return profile

    async def get_referral_tree(self, user_id: str, depth: int) -> ReferralTreeResponse:
        rows = await self.repository.get_referral_tree_rows(user_id, depth)
        if not rows:
            raise CSREException(
                ErrorCode.USER_NOT_FOUND,
                "User not found",
                status.HTTP_404_NOT_FOUND,
            )

        nodes = {
            row["id"]: ReferralTreeNode(id=row["id"], username=row["username"], children=[])
            for row in rows
        }
        root_row = rows[0]
        for row in rows[1:]:
            parent_id = row["referrer_id"]
            if parent_id in nodes:
                nodes[parent_id].children.append(nodes[row["id"]])

        return ReferralTreeResponse(
            root=root_row["id"],
            tree=nodes[root_row["id"]],
            total_nodes=len(rows),
            depth_queried=depth,
        )

    async def _ensure_unique_identity(self, email: str, username: str) -> None:
        if await self.repository.get_user_by_email(email):
            raise CSREException(
                ErrorCode.EMAIL_EXISTS,
                "Email already registered",
                status.HTTP_409_CONFLICT,
            )
        if await self.repository.get_user_by_username(username):
            raise CSREException(
                ErrorCode.USERNAME_EXISTS,
                "Username already registered",
                status.HTTP_409_CONFLICT,
            )

    async def _generate_unique_referral_code(self, username: str) -> str:
        prefix = re.sub(r"[^A-Z0-9]", "", username.upper())[:5] or "USER"
        for _ in range(5):
            code = f"{prefix}-{self._random_base36(4)}"
            if not await self.repository.referral_code_exists(code):
                return code

        while True:
            fallback_code = f"{uuid4().hex[:5].upper()}-{uuid4().hex[5:9].upper()}"
            if not await self.repository.referral_code_exists(fallback_code):
                return fallback_code

    async def _issue_token_pair(self, user_id: str) -> TokenResponse:
        access = create_access_token(user_id, self.settings)
        refresh = create_refresh_token(user_id, self.settings)
        await self.repository.store_refresh_token(
            refresh.jti,
            user_id,
            self.settings.refresh_token_ttl_seconds,
        )
        return TokenResponse(
            access_token=access.token,
            refresh_token=refresh.token,
            expires_in=access.expires_in,
        )

    def _map_integrity_error(self, exc: IntegrityError) -> CSREException:
        message = str(exc).lower()
        if "email" in message:
            return CSREException(
                ErrorCode.EMAIL_EXISTS,
                "Email already registered",
                status.HTTP_409_CONFLICT,
            )
        if "username" in message:
            return CSREException(
                ErrorCode.USERNAME_EXISTS,
                "Username already registered",
                status.HTTP_409_CONFLICT,
            )
        if "referred_id" in message:
            return CSREException(
                ErrorCode.DUPLICATE_REFERRAL,
                "User already has a referrer",
                status.HTTP_409_CONFLICT,
            )
        return CSREException(
            ErrorCode.VALIDATION_ERROR,
            "A database integrity constraint was violated",
            status.HTTP_409_CONFLICT,
        )

    @staticmethod
    def _random_base36(length: int) -> str:
        return "".join(secrets.choice(BASE36_ALPHABET) for _ in range(length))


async def get_user_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> AsyncIterator[UserService]:
    repository = UserRepository(
        session=session,
        redis=request.app.state.redis,
        neo4j_driver=request.app.state.neo4j_driver,
        settings=request.app.state.settings,
    )
    yield UserService(repository)
