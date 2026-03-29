from redis.asyncio import Redis

from csre.core.config import Settings


def init_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


async def close_redis_client(client: Redis) -> None:
    await client.aclose()


async def redis_healthcheck(client: Redis) -> bool:
    try:
        return bool(await client.ping())
    except Exception:
        return False

