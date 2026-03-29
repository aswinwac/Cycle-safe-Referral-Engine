import asyncio
from csre.db.base import Base
from csre.db.postgres import init_postgres_engine
from csre.core.config import get_settings
# Import all models to ensure they are registered with Base.metadata
from csre.db.models import (
    UserRecord,
    ReferralRecord,
    RewardRecord,
    FraudEventRecord,
    ActivityEventRecord,
    GraphSyncQueueRecord,
)

async def create_tables():
    settings = get_settings()
    engine = init_postgres_engine(settings)
    print(f"Connecting to {settings.postgres_host}...")
    async with engine.begin() as conn:
        print("Creating tables...")
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Tables created successfully!")

if __name__ == "__main__":
    asyncio.run(create_tables())
