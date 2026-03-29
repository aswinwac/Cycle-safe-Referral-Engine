import asyncio
import re
from collections.abc import AsyncIterator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from csre.db.base import Base
from csre.db.models import FraudEventRecord, UserRecord
from csre.main import app
from csre.modules.user.repository import UserRepository
from csre.modules.user.service import UserService, get_user_service


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                deleted += 1
            self.expirations.pop(key, None)
        return deleted

    async def expire(self, key: str, ttl: int) -> bool:
        if key not in self.values:
            return False
        self.expirations[key] = ttl
        return True

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])


class FakeNeo4jResult:
    async def consume(self) -> None:
        return None


class FakeNeo4jSession:
    def __init__(self, store: "FakeNeo4jDriver") -> None:
        self.store = store

    async def __aenter__(self) -> "FakeNeo4jSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run(self, query: str, **params) -> FakeNeo4jResult:
        self.store.calls.append({"query": query, "params": params})
        return FakeNeo4jResult()


class FakeNeo4jDriver:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def session(self, database: str | None = None) -> FakeNeo4jSession:
        _ = database
        return FakeNeo4jSession(self)


@pytest.fixture
def user_client() -> Generator[tuple[TestClient, FakeRedis, FakeNeo4jDriver, async_sessionmaker], None, None]:
    redis = FakeRedis()
    neo4j_driver = FakeNeo4jDriver()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())

    async def override_get_user_service() -> AsyncIterator[UserService]:
        async with session_factory() as session:
            yield UserService(
                UserRepository(
                    session=session,
                    redis=redis,
                    neo4j_driver=neo4j_driver,
                    settings=app.state.settings,
                )
            )

    app.dependency_overrides[get_user_service] = override_get_user_service

    with TestClient(app) as client:
        yield client, redis, neo4j_driver, session_factory

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def test_register_user_returns_tokens_and_referral_code(
    user_client: tuple[TestClient, FakeRedis, FakeNeo4jDriver, async_sessionmaker],
) -> None:
    client, redis, neo4j_driver, _ = user_client

    response = client.post(
        "/api/v1/users/register",
        json={
            "email": "Alice@example.com",
            "username": "alice_wonder",
            "password": "supersecret123",
            "ip_address": "203.0.113.10",
            "device_hash": "device-001",
        },
    )

    payload = response.json()
    user = payload["data"]["user"]

    assert response.status_code == 201
    assert payload["success"] is True
    assert user["email"] == "alice@example.com"
    assert re.fullmatch(r"[A-Z0-9]{1,5}-[A-Z0-9]{4}", user["referral_code"])
    assert payload["data"]["tokens"]["access_token"]
    assert payload["data"]["tokens"]["refresh_token"]
    assert redis.values[f"user:code:{user['referral_code']}"] == user["id"]
    assert neo4j_driver.calls


def test_register_with_valid_referral_code_sets_referrer_and_supports_lookup_and_tree(
    user_client: tuple[TestClient, FakeRedis, FakeNeo4jDriver, async_sessionmaker],
) -> None:
    client, _, _, _ = user_client

    root = client.post(
        "/api/v1/users/register",
        json={
            "email": "root@example.com",
            "username": "root_user",
            "password": "supersecret123",
        },
    ).json()["data"]
    child = client.post(
        "/api/v1/users/register",
        json={
            "email": "child@example.com",
            "username": "child_user",
            "password": "supersecret123",
            "referral_code": root["user"]["referral_code"],
        },
    ).json()["data"]
    grandchild = client.post(
        "/api/v1/users/register",
        json={
            "email": "grandchild@example.com",
            "username": "grandchild_user",
            "password": "supersecret123",
            "referral_code": child["user"]["referral_code"],
        },
    ).json()["data"]

    auth_headers = {"Authorization": f"Bearer {root['tokens']['access_token']}"}

    lookup_response = client.get(
        f"/api/v1/users/by-code/{root['user']['referral_code']}",
        headers=auth_headers,
    )
    profile_response = client.get(f"/api/v1/users/{root['user']['id']}", headers=auth_headers)
    tree_response = client.get(
        f"/api/v1/users/{root['user']['id']}/referral-tree?depth=3",
        headers=auth_headers,
    )

    assert child["user"]["referrer_id"] == root["user"]["id"]
    assert grandchild["user"]["referrer_id"] == child["user"]["id"]
    assert lookup_response.status_code == 200
    assert lookup_response.json()["data"]["user_id"] == root["user"]["id"]

    profile_payload = profile_response.json()["data"]
    assert profile_response.status_code == 200
    assert profile_payload["stats"]["total_referrals"] == 1
    assert profile_payload["stats"]["valid_referrals"] == 1
    assert profile_payload["stats"]["fraud_referrals"] == 0

    tree_payload = tree_response.json()["data"]
    assert tree_response.status_code == 200
    assert tree_payload["total_nodes"] == 3
    assert tree_payload["tree"]["children"][0]["id"] == child["user"]["id"]
    assert tree_payload["tree"]["children"][0]["children"][0]["id"] == grandchild["user"]["id"]


def test_duplicate_email_returns_email_exists(
    user_client: tuple[TestClient, FakeRedis, FakeNeo4jDriver, async_sessionmaker],
) -> None:
    client, _, _, _ = user_client

    client.post(
        "/api/v1/users/register",
        json={
            "email": "duplicate@example.com",
            "username": "first_user",
            "password": "supersecret123",
        },
    )
    duplicate_response = client.post(
        "/api/v1/users/register",
        json={
            "email": "duplicate@example.com",
            "username": "second_user",
            "password": "supersecret123",
        },
    )

    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "EMAIL_EXISTS"


def test_invalid_referral_code_returns_invalid_code(
    user_client: tuple[TestClient, FakeRedis, FakeNeo4jDriver, async_sessionmaker],
) -> None:
    client, _, _, _ = user_client

    response = client.post(
        "/api/v1/users/register",
        json={
            "email": "invalid-code@example.com",
            "username": "invalid_code_user",
            "password": "supersecret123",
            "referral_code": "NOPE-1234",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CODE"


def test_refresh_token_rotates_tokens(
    user_client: tuple[TestClient, FakeRedis, FakeNeo4jDriver, async_sessionmaker],
) -> None:
    client, _, _, _ = user_client

    registration = client.post(
        "/api/v1/users/register",
        json={
            "email": "refresh@example.com",
            "username": "refresh_user",
            "password": "supersecret123",
        },
    ).json()["data"]

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": registration["tokens"]["refresh_token"]},
    )

    assert refresh_response.status_code == 200
    refreshed_tokens = refresh_response.json()["data"]
    assert refreshed_tokens["access_token"] != registration["tokens"]["access_token"]
    assert refreshed_tokens["refresh_token"] != registration["tokens"]["refresh_token"]


def test_deactivated_referrer_code_is_invalid(
    user_client: tuple[TestClient, FakeRedis, FakeNeo4jDriver, async_sessionmaker],
) -> None:
    client, _, _, session_factory = user_client

    root = client.post(
        "/api/v1/users/register",
        json={
            "email": "deactivated-root@example.com",
            "username": "deactivated_root",
            "password": "supersecret123",
        },
    ).json()["data"]

    async def deactivate_root() -> None:
        async with session_factory() as session:
            user = await session.get(UserRecord, root["user"]["id"])
            assert user is not None
            user.status = "DEACTIVATED"
            await session.commit()

    asyncio.run(deactivate_root())

    response = client.post(
        "/api/v1/users/register",
        json={
            "email": "blocked@example.com",
            "username": "blocked_user",
            "password": "supersecret123",
            "referral_code": root["user"]["referral_code"],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CODE"


def test_duplicate_ip_creates_fraud_signal_without_blocking_registration(
    user_client: tuple[TestClient, FakeRedis, FakeNeo4jDriver, async_sessionmaker],
) -> None:
    client, _, _, session_factory = user_client

    client.post(
        "/api/v1/users/register",
        json={
            "email": "signal-1@example.com",
            "username": "signal_user_1",
            "password": "supersecret123",
            "ip_address": "203.0.113.55",
        },
    )
    response = client.post(
        "/api/v1/users/register",
        json={
            "email": "signal-2@example.com",
            "username": "signal_user_2",
            "password": "supersecret123",
            "ip_address": "203.0.113.55",
        },
    )

    async def count_signals() -> int:
        async with session_factory() as session:
            result = await session.execute(select(FraudEventRecord))
            return len(result.scalars().all())

    assert response.status_code == 201
    assert asyncio.run(count_signals()) == 1
