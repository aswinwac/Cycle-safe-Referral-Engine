from fastapi import APIRouter, Depends, Response, status

from csre.core.security import TokenPayload, require_access_token, require_admin_api_key
from csre.modules.referral.schemas import ReferralAdminReviewRequest, ReferralClaimRequest
from csre.modules.referral.service import ReferralService, get_referral_service
from csre.schemas.envelope import success_response

router = APIRouter(prefix="/referrals", tags=["referrals"])


@router.post("/claim", status_code=status.HTTP_201_CREATED)
async def claim_referral(
    payload: ReferralClaimRequest,
    response: Response,
    service: ReferralService = Depends(get_referral_service),
    token: TokenPayload = Depends(require_access_token),
):
    """
    Claim a referral using a referral code (JWT subject = claimant).
    """
    user_id = token.sub

    result = await service.claim_referral(
        user_id=user_id,
        referral_code=payload.referral_code,
        ip_address=str(payload.ip_address) if payload.ip_address else None,
        device_hash=payload.device_hash,
    )

    response.headers["Location"] = f"/api/v1/referrals/{result.referral.id}"

    return success_response(result)


@router.get("/by-user/{user_id}")
async def get_user_referrals(
    user_id: str,
    role: str = "referrer",
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
    service: ReferralService = Depends(get_referral_service),
    _: TokenPayload = Depends(require_access_token),
):
    """Paginated referrals where the user is referrer or referred."""
    result = await service.get_user_referrals(
        user_id=user_id,
        role=role,
        status=status,
        page=page,
        limit=limit,
    )
    return success_response(result)


@router.patch("/{referral_id}/review", status_code=status.HTTP_200_OK)
async def admin_review_referral(
    referral_id: str,
    payload: ReferralAdminReviewRequest,
    service: ReferralService = Depends(get_referral_service),
    _: None = Depends(require_admin_api_key),
):
    """Admin override for referral investigation (X-Admin-Key + ADMIN_API_KEY)."""
    result = await service.admin_review_referral(referral_id=referral_id, payload=payload)
    return success_response(result)


@router.get("/{referral_id}")
async def get_referral(
    referral_id: str,
    service: ReferralService = Depends(get_referral_service),
    _: TokenPayload = Depends(require_access_token),
):
    """Single referral by id (nested referrer/referred per spec)."""
    result = await service.get_referral(referral_id)
    return success_response(result)
