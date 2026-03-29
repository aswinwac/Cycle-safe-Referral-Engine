from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime

class RewardEventResponse(BaseModel):
    id: str
    referral_id: str
    trigger_user: Dict[str, str]
    level: int
    reward_type: str
    amount: float
    status: str
    issued_at: Optional[str]

class RewardLedgerResponse(BaseModel):
    user_id: str
    total_earned: float
    pending: float
    rewards: List[RewardEventResponse]
    pagination: Dict[str, int]

class RewardConfigLevel(BaseModel):
    level: int
    value: float

class RewardConfigData(BaseModel):
    id: str
    name: str
    max_depth: int
    reward_type: str
    level_configs: List[RewardConfigLevel]
    is_active: bool

class RewardConfigResponse(BaseModel):
    active_config: RewardConfigData

class RewardConfigPayload(BaseModel):
    name: str
    max_depth: int
    reward_type: str
    level_configs: List[RewardConfigLevel]

class RewardSummaryLevel(BaseModel):
    level: int
    count: int
    amount: float

class RewardSummaryResponse(BaseModel):
    total_rewards_issued: int
    total_amount_distributed: float
    pending_amount: float
    by_level: List[RewardSummaryLevel]
