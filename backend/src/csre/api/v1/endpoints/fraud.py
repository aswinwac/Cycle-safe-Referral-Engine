from fastapi import APIRouter, Depends, Query, Path
from csre.schemas.envelope import success_response
from csre.modules.fraud.service import FraudService, get_fraud_service
from csre.modules.fraud.schemas import FraudReviewRequest

router = APIRouter(prefix="/fraud", tags=["fraud"])

@router.get("/events")
async def get_events(
    page: int = Query(default=1),
    limit: int = Query(default=20),
    reason: str = Query(default=None),
    reviewed: bool = Query(default=None),
    severity: int = Query(default=None),
    service: FraudService = Depends(get_fraud_service)
):
    result = await service.get_events(page, limit, reason, reviewed, severity)
    return success_response(result)

@router.patch("/events/{event_id}/review")
async def review_event(
    payload: FraudReviewRequest,
    event_id: str = Path(...),
    service: FraudService = Depends(get_fraud_service)
):
    # Mocking user_id for the admin doing review
    result = await service.review_event(event_id, payload, "admin-user-id")
    return success_response(result)

@router.get("/stats")
async def get_stats(
    service: FraudService = Depends(get_fraud_service)
):
    result = await service.get_stats()
    return success_response(result)

@router.get("/config")
async def get_config(
    service: FraudService = Depends(get_fraud_service)
):
    result = await service.get_config()
    return success_response(result)
