from fastapi import APIRouter, Depends, Query, Path
from csre.schemas.envelope import success_response
from csre.modules.reward.service import RewardService, get_reward_service

router = APIRouter(prefix="/rewards", tags=["rewards"])

@router.get("/ledger/{user_id}")
async def get_ledger(
    user_id: str = Path(...),
    status: str = Query(default=None),
    page: int = Query(default=1),
    limit: int = Query(default=20),
    service: RewardService = Depends(get_reward_service)
):
    result = await service.get_ledger(user_id, status, page, limit)
    return success_response(result)

@router.get("/config")
async def get_config(
    service: RewardService = Depends(get_reward_service)
):
    result = await service.get_config()
    return success_response(result)

@router.get("/summary")
async def get_summary(
    service: RewardService = Depends(get_reward_service)
):
    result = await service.get_summary()
    return success_response(result)
