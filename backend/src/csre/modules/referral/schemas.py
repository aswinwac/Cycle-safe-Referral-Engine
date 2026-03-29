from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReferralClaimRequest(BaseModel):
    referral_code: str = Field(min_length=4, max_length=20)
    ip_address: Optional[str] = None
    device_hash: Optional[str] = None


class ReferralUserRef(BaseModel):
    id: str
    username: str


class ReferralDetailResponse(BaseModel):
    """Full referral row (claim + list with audit fields)."""

    id: str
    referrer_id: str
    referrer_username: str
    referred_id: str
    referred_username: str
    status: str
    depth: int
    ip_address: Optional[str] = None
    device_hash: Optional[str] = None
    fraud_reason: Optional[str] = None
    fraud_metadata: dict = Field(default_factory=dict)
    created_at: str
    resolved_at: Optional[str] = None


class ReferralGetResponse(BaseModel):
    """Public referral shape per referral.spec (nested users)."""

    id: str
    referrer: ReferralUserRef
    referred: ReferralUserRef
    status: str
    depth: int
    fraud_reason: Optional[str] = None
    fraud_metadata: dict = Field(default_factory=dict)
    created_at: str
    resolved_at: Optional[str] = None


class ReferralResponse(BaseModel):
    referral: ReferralDetailResponse
    rewards_triggered: bool
    reward_job_id: Optional[str] = None


class UserReferralsResponse(BaseModel):
    referrals: list[ReferralGetResponse]
    pagination: dict


class ReferralAdminReviewRequest(BaseModel):
    status: Literal["PENDING", "VALID", "REJECTED", "FRAUD"]
    fraud_reason: Optional[str] = None
    notes: Optional[str] = None
