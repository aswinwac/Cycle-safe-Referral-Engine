from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime

class FraudEventResponse(BaseModel):
    id: str
    user: Dict[str, str]
    referral_id: Optional[str]
    reason: str
    severity: int
    metadata: Dict[str, Any]
    reviewed: bool
    created_at: str

class FraudEventsListResponse(BaseModel):
    events: List[FraudEventResponse]
    pagination: Dict[str, int]

class FraudReviewRequest(BaseModel):
    reviewed: bool
    review_notes: str
    action: str

class FraudReviewResponse(BaseModel):
    event_id: str
    reviewed: bool
    action_taken: str

class FraudStatsResponse(BaseModel):
    total_fraud_events: int
    by_reason: Dict[str, int]
    unreviewed_high_severity: int
    fraud_rate_7d: float

class FraudConfigResponse(BaseModel):
    velocity_limits: Dict[str, int]
    duplicate_detection: Dict[str, int]
    rejection_rate_threshold: float
    auto_suspend_on_cycle: bool
