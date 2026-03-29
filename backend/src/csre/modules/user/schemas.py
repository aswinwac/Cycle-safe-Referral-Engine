from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator, IPvAnyAddress

Username = Annotated[
    str,
    StringConstraints(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$"),
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=255)]
ReferralCode = Annotated[
    str,
    StringConstraints(min_length=6, max_length=20, pattern=r"^[A-Z0-9]{1,5}-[A-Z0-9]{4}$"),
]
DeviceHash = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class UserRegistrationRequest(BaseModel):
    email: EmailStr
    username: Username
    password: Password
    referral_code: ReferralCode | None = None
    ip_address: IPvAnyAddress | None = None
    device_hash: DeviceHash | None = None

    @field_validator("referral_code")
    @classmethod
    def normalize_referral_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class TokenRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class RegisteredUserResponse(BaseModel):
    id: str
    email: EmailStr
    username: str
    referral_code: str
    referrer_id: str | None = None
    status: str
    created_at: datetime


class RegistrationResponse(BaseModel):
    user: RegisteredUserResponse
    tokens: TokenResponse


class ReferrerSummary(BaseModel):
    id: str
    username: str


class UserStatsResponse(BaseModel):
    total_referrals: int = 0
    valid_referrals: int = 0
    fraud_referrals: int = 0
    total_rewards_earned: Decimal = Decimal("0")


class UserProfileResponse(BaseModel):
    id: str
    username: str
    referral_code: str
    referrer: ReferrerSummary | None = None
    stats: UserStatsResponse
    status: str
    created_at: datetime


class ReferralCodeLookupResponse(BaseModel):
    user_id: str
    username: str
    referral_code: str


class ReferralTreeNode(BaseModel):
    id: str
    username: str
    children: list[ReferralTreeNode] = Field(default_factory=list)


class ReferralTreeResponse(BaseModel):
    root: str
    tree: ReferralTreeNode
    total_nodes: int
    depth_queried: int


ReferralTreeNode.model_rebuild()
