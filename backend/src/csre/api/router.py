from fastapi import APIRouter

from csre.api.v1.endpoints import auth, dashboard, fraud, health, referrals, rewards, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(health.router)
api_router.include_router(users.router)
api_router.include_router(referrals.router)
api_router.include_router(rewards.router)
api_router.include_router(fraud.router)
api_router.include_router(dashboard.router)
