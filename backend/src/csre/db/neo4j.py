from neo4j import AsyncDriver, AsyncGraphDatabase

from csre.core.config import Settings


def init_neo4j_driver(settings: Settings) -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


async def close_neo4j_driver(driver: AsyncDriver) -> None:
    await driver.close()


async def neo4j_healthcheck(driver: AsyncDriver) -> bool:
    try:
        await driver.verify_connectivity()
    except Exception:
        return False
    return True

