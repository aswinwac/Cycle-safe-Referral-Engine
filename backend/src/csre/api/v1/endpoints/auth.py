from fastapi import APIRouter, Depends

from csre.modules.user.schemas import TokenRefreshRequest
from csre.modules.user.service import UserService, get_user_service
from csre.schemas.envelope import success_response

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/refresh")
async def refresh_tokens(
    payload: TokenRefreshRequest,
    service: UserService = Depends(get_user_service),
):
    tokens = await service.refresh_tokens(payload)
    return success_response(tokens)
