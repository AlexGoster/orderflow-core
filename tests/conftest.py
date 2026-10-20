import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_session
from app.main import app
from app.schemas import UserCreate
from app.services.users import register_user


@pytest.fixture
async def engine(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    if make_url(url).get_backend_name() == "postgresql" and not (
        make_url(url).database or ""
    ).endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must point to a dedicated database ending in _test")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def registered_user(client: AsyncClient) -> dict[str, str]:
    email = "user@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret-pass-1", "full_name": "Test User"},
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "secret-pass-1"}
    )
    data = resp.json()
    return {"email": email, "token": data["access_token"]}


@pytest.fixture
async def auth_headers(registered_user: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered_user['token']}"}


@pytest.fixture
async def admin_headers(client, session_factory):
    async with session_factory() as session:
        await register_user(
            session,
            UserCreate(email="admin@example.com", password="admin-test-password"),
            is_admin=True,
        )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin-test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
