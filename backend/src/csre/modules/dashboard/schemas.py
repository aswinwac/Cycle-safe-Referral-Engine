from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

class MetricsResponse(BaseModel):
    window: str
    generated_at: str
    users: dict
    referrals: dict
    rewards: dict
    fraud: dict
    system: dict

class FraudEventResponse(BaseModel):
    id: str
    user: dict
    reason: str
    severity: int
    severity_label: str
    referral_attempt: dict
    metadata: dict
    reviewed: bool
    created_at: str

class FraudPanelResponse(BaseModel):
    events: List[FraudEventResponse]
    pagination: dict
    summary: dict

class ActivityEventResponse(BaseModel):
    id: str
    event_type: str
    label: str
    actor: dict
    target: Optional[dict]
    payload: dict
    created_at: str

class ActivityFeedResponse(BaseModel):
    events: List[ActivityEventResponse]

class GraphResponse(BaseModel):
    root_user_id: str
    depth: int
    nodes: List[dict]
    edges: List[dict]
    stats: dict
