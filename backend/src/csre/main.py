from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from csre.api.router import api_router
from csre.core.config import get_settings
from csre.core.exception_handlers import install_exception_handlers
from csre.core.logging import configure_logging
from csre.db.neo4j import close_neo4j_driver, init_neo4j_driver
from csre.db.postgres import build_session_factory, close_postgres_engine, init_postgres_engine
from csre.db.redis import close_redis_client, init_redis_client

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings)
    app.state.settings = settings
    app.state.postgres_engine = init_postgres_engine(settings)
    app.state.session_factory = build_session_factory(app.state.postgres_engine)
    app.state.redis = init_redis_client(settings)
    app.state.neo4j_driver = init_neo4j_driver(settings)
    yield
    await close_redis_client(app.state.redis)
    await close_neo4j_driver(app.state.neo4j_driver)
    await close_postgres_engine(app.state.postgres_engine)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    lifespan=lifespan,
)
install_exception_handlers(app)
app.include_router(api_router, prefix=settings.api_v1_prefix)
app.mount("/metrics", make_asgi_app())
