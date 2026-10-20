import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models import Product


async def make_product(client, admin_headers, sku="regression", stock=5, price=10):
    response = await client.post(
        "/api/v1/products",
        headers=admin_headers,
        json={"sku": sku, "name": "Test", "price": price, "stock": stock},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_status_owner_and_repeat(client: AsyncClient, auth_headers, admin_headers):
    product_id = await make_product(client, admin_headers)
    order = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product_id, "quantity": 1}]},
    )
    url = f"/api/v1/orders/{order.json()['id']}/status?new_status=cancelled"
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "test-password",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "other@example.com",
            "password": "test-password",
        },
    )
    other = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.patch(url, headers=other)).status_code == 404
    assert (await client.get("/api/v1/orders", headers=other)).json() == []
    for _ in range(2):
        response = await client.patch(url, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
    assert (
        await client.patch("/api/v1/orders/999/status?new_status=paid", headers=auth_headers)
    ).status_code == 404


@pytest.mark.parametrize("subject", ["abc", "0", "-1", "9999999999999999999999"])
async def test_invalid_subject_is_401(client: AsyncClient, subject):
    response = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {create_access_token(subject)}",
        },
    )
    assert response.status_code == 401


@pytest.mark.parametrize("kind", ["expired", "missing_exp", "wrong_key", "deleted_user"])
async def test_invalid_tokens(client: AsyncClient, auth_headers, kind):
    now = datetime.now(UTC)
    user = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    subject = "123" if kind == "deleted_user" else str(user["id"])
    payload = {"sub": subject, "iat": now, "exp": now + timedelta(minutes=1)}
    key = get_settings().secret_key
    if kind == "expired":
        payload["exp"] = now - timedelta(seconds=1)
    if kind == "missing_exp":
        del payload["exp"]
    if kind == "wrong_key":
        key = "another-test-key-with-at-least-32-bytes"
    token = jwt.encode(payload, key, algorithm="HS256")
    assert (
        await client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
            },
        )
    ).status_code == 401


@pytest.mark.parametrize("failure", ["missing", "stock", "duplicate", "overflow"])
async def test_failed_order_rolls_back(client: AsyncClient, auth_headers, admin_headers, failure):
    product_id = await make_product(
        client, admin_headers, price=99999999.99 if failure == "overflow" else 10
    )
    items = [{"product_id": product_id, "quantity": 2}]
    if failure == "missing":
        items.append({"product_id": 999, "quantity": 1})
    elif failure in ("stock", "duplicate"):
        items.append({"product_id": product_id, "quantity": 4})
    response = await client.post("/api/v1/orders", headers=auth_headers, json={"items": items})
    assert (
        response.status_code
        == {"missing": 404, "stock": 409, "duplicate": 409, "overflow": 422}[failure]
    )
    assert (await client.get(f"/api/v1/products/{product_id}")).json()["stock"] == 5
    assert (await client.get("/api/v1/orders", headers=auth_headers)).json() == []


@pytest.mark.parametrize("price", ["0.001", "100000000", "Infinity", "NaN", -1])
async def test_invalid_prices(client: AsyncClient, admin_headers, price):
    response = await client.post(
        "/api/v1/products",
        headers=admin_headers,
        json={
            "sku": "invalid",
            "name": "Test",
            "price": price,
        },
    )
    assert response.status_code == 422


async def test_validation_and_missing(client: AsyncClient, auth_headers):
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "invalid",
                "password": "short",
            },
        )
    ).status_code == 422
    assert (
        await client.patch("/api/v1/orders/1/status?new_status=unknown", headers=auth_headers)
    ).status_code == 422


@pytest.mark.parametrize("ident", [0, -1, 2_147_483_648])
async def test_invalid_ids(client: AsyncClient, auth_headers, ident):
    assert (await client.get(f"/api/v1/products/{ident}")).status_code == 422
    assert (await client.get(f"/api/v1/orders/{ident}", headers=auth_headers)).status_code == 422
    assert (
        await client.patch(f"/api/v1/orders/{ident}/status?new_status=paid", headers=auth_headers)
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/orders",
            headers=auth_headers,
            json={"items": [{"product_id": ident, "quantity": 1}]},
        )
    ).status_code == 422
    assert (await client.get("/api/v1/products?limit=0")).status_code == 422
    assert (await client.get("/api/v1/orders/999", headers=auth_headers)).status_code == 404
    assert (
        await client.post("/api/v1/orders", headers=auth_headers, json={"items": []})
    ).status_code == 422


async def test_concurrent_stock(
    client: AsyncClient, auth_headers, admin_headers, engine, monkeypatch
):
    product_id = await make_product(client, admin_headers, stock=1)
    if engine.dialect.name == "postgresql":
        # Both transactions must read the last unit before either attempts to reserve it.
        # SQLite serializes writes at the initial order INSERT, so no barrier there.
        original_get = AsyncSession.get
        ready = asyncio.Event()
        reads = 0

        async def synchronized_get(session, entity, ident, **kwargs):
            nonlocal reads
            result = await original_get(session, entity, ident, **kwargs)
            if entity is Product:
                reads += 1
                if reads == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=10)
            return result

        monkeypatch.setattr(AsyncSession, "get", synchronized_get)
    responses = await asyncio.gather(
        *[
            client.post(
                "/api/v1/orders",
                headers=auth_headers,
                json={"items": [{"product_id": product_id, "quantity": 1}]},
            )
            for _ in range(2)
        ]
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert (await client.get(f"/api/v1/products/{product_id}")).json()["stock"] == 0
    assert len((await client.get("/api/v1/orders", headers=auth_headers)).json()) == 1


@pytest.mark.parametrize("resource", ["products", "auth/register"])
async def test_concurrent_duplicates(client: AsyncClient, admin_headers, resource):
    payload = (
        {"sku": "duplicate", "name": "Test", "price": 10}
        if resource == "products"
        else {"email": "duplicate@example.com", "password": "test-password"}
    )
    responses = await asyncio.gather(
        *[client.post(f"/api/v1/{resource}", json=payload, headers=admin_headers) for _ in range(2)]
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
