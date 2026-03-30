from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from csre.core.security import TokenPayload, require_access_token
from csre.modules.user.schemas import UserRegistrationRequest, ReferralCodeLookupResponse
from csre.modules.user.service import UserService, get_user_service
from csre.schemas.envelope import success_response

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[ReferralCodeLookupResponse])
async def list_users(
    service: UserService = Depends(get_user_service),
):
    """List all users with their referral codes (Admin/Dashboard use)"""
    return await service.list_all_users()



@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserRegistrationRequest,
    service: UserService = Depends(get_user_service),
):
    result = await service.register_user(payload)
    return success_response(result)


@router.get("/by-code/{referral_code}")
async def get_user_by_referral_code(
    referral_code: str,
    service: UserService = Depends(get_user_service),
    _: TokenPayload = Depends(require_access_token),
):
    result = await service.get_user_by_code(referral_code)
    return success_response(result)


@router.get("/{user_id}/referral-tree")
async def get_user_referral_tree(
    user_id: UUID,
    depth: int = Query(default=3, ge=1, le=5),
    service: UserService = Depends(get_user_service),
    _: TokenPayload = Depends(require_access_token),
):
    result = await service.get_referral_tree(str(user_id), depth)
    return success_response(result)


@router.get("/{user_id}")
async def get_user_profile(
    user_id: UUID,
    service: UserService = Depends(get_user_service),
    _: TokenPayload = Depends(require_access_token),
):
    result = await service.get_profile(str(user_id))
    return success_response(result)
