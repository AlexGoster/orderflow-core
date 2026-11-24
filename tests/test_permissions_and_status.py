import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app import cli
from app.core.exceptions import ConflictError
from app.models import User
from app.services import orders as orders_service


async def test_admin_bootstrap_does_not_promote_existing(client, session_factory, monkeypatch):
    monkeypatch.setattr(cli, "get_session_factory", lambda: session_factory)
    user = await cli.create_admin("bootstrap@example.com", "admin-test-password")
    assert user.is_admin is True
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "bootstrap@example.com",
            "password": "admin-test-password",
        },
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["is_admin"] is True
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ordinary@example.com",
            "password": "ordinary-password",
        },
    )
    with pytest.raises(ConflictError):
        await cli.create_admin("ordinary@example.com", "admin-test-password")
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "ordinary@example.com",
            "password": "ordinary-password",
        },
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["is_admin"] is False


async def test_admin_role_is_checked_against_database(client, admin_headers, session_factory):
    async with session_factory() as session:
        await session.execute(
            update(User).where(User.email == "admin@example.com").values(is_admin=False)
        )
        await session.commit()
    assert (
        await client.post(
            "/api/v1/products",
            headers=admin_headers,
            json={
                "sku": "revoked",
                "name": "Test",
                "price": 10,
            },
        )
    ).status_code == 403


async def create_order(client, auth_headers, admin_headers, *, quantity=2):
    product = await client.post(
        "/api/v1/products",
        headers=admin_headers,
        json={
            "sku": "status-test",
            "name": "Test",
            "price": "10.00",
            "stock": 5,
        },
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    order = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": quantity}],
        },
    )
    assert order.status_code == 201
    return product_id, order.json()["id"]


async def test_products_require_admin(client: AsyncClient, auth_headers, admin_headers):
    body = {"sku": "restricted", "name": "Test", "price": 10}
    assert (await client.post("/api/v1/products", json=body)).status_code == 401
    assert (
        await client.post("/api/v1/products", json=body, headers=auth_headers)
    ).status_code == 403
    assert (await client.get("/api/v1/products")).json() == []
    assert (
        await client.post("/api/v1/products", json=body, headers=admin_headers)
    ).status_code == 201
    assert (await client.get("/api/v1/products")).status_code == 200


async def test_registration_cannot_grant_admin(client: AsyncClient):
    body = {"email": "escalation@example.com", "password": "test-password", "is_admin": True}
    response = await client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201
    assert response.json()["is_admin"] is False
    login = await client.post("/api/v1/auth/login", json=body)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["is_admin"] is False
    assert (
        await client.post(
            "/api/v1/products",
            headers=headers,
            json={
                "sku": "blocked",
                "name": "Test",
                "price": 10,
            },
        )
    ).status_code == 403


async def test_admin_lifecycle_and_customer_permissions(client, auth_headers, admin_headers):
    product_id, order_id = await create_order(client, auth_headers, admin_headers)
    url = f"/api/v1/orders/{order_id}/status"
    for target in ("paid", "shipped", "pending"):
        assert (
            await client.patch(url, params={"new_status": target}, headers=auth_headers)
        ).status_code == 403
    assert (
        await client.patch(url, params={"new_status": "shipped"}, headers=admin_headers)
    ).status_code == 409
    for target in ("paid", "paid", "shipped", "shipped"):
        response = await client.patch(url, params={"new_status": target}, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["status"] == target
    for target in ("pending", "paid", "cancelled"):
        assert (
            await client.patch(url, params={"new_status": target}, headers=admin_headers)
        ).status_code == 409
    assert (
        await client.patch(url, params={"new_status": "cancelled"}, headers=auth_headers)
    ).status_code == 403
    assert (await client.get(f"/api/v1/products/{product_id}")).json()["stock"] == 3
    assert (
        await client.get(f"/api/v1/orders/{order_id}", headers=admin_headers)
    ).status_code == 200
    assert len((await client.get("/api/v1/orders", headers=admin_headers)).json()) == 1


@pytest.mark.parametrize("paid", [False, True])
async def test_cancel_returns_stock_once(client, auth_headers, admin_headers, paid):
    product_id, order_id = await create_order(client, auth_headers, admin_headers)
    url = f"/api/v1/orders/{order_id}/status"
    if paid:
        assert (
            await client.patch(url, params={"new_status": "paid"}, headers=admin_headers)
        ).status_code == 200
        assert (
            await client.patch(url, params={"new_status": "cancelled"}, headers=auth_headers)
        ).status_code == 403
    actor = admin_headers if paid else auth_headers
    for _ in range(2):
        response = await client.patch(url, params={"new_status": "cancelled"}, headers=actor)
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert response.json()["total"] == 20
        assert (await client.get(f"/api/v1/products/{product_id}")).json()["stock"] == 5
    assert (
        await client.patch(url, params={"new_status": "paid"}, headers=admin_headers)
    ).status_code == 409
    # The returned units can be reserved by a subsequent order.
    assert (
        await client.post(
            "/api/v1/orders",
            headers=auth_headers,
            json={
                "items": [{"product_id": product_id, "quantity": 5}],
            },
        )
    ).status_code == 201


@pytest.mark.parametrize("competing_status", ["cancelled", "paid"])
async def test_concurrent_cancellation(
    client, auth_headers, admin_headers, monkeypatch, competing_status
):
    product_id, order_id = await create_order(client, auth_headers, admin_headers)
    original_get = orders_service.get_order
    ready = asyncio.Event()
    reads = 0

    async def synchronized_get(*args, **kwargs):
        nonlocal reads
        order = await original_get(*args, **kwargs)
        reads += 1
        if reads == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=10)
        return order

    monkeypatch.setattr(orders_service, "get_order", synchronized_get)
    url = f"/api/v1/orders/{order_id}/status"
    responses = await asyncio.gather(
        client.patch(url, params={"new_status": "cancelled"}, headers=auth_headers),
        client.patch(url, params={"new_status": competing_status}, headers=admin_headers),
    )
    if competing_status == "cancelled":
        assert [r.status_code for r in responses] == [200, 200]
        expected_stock = 5
    else:
        assert sorted(r.status_code for r in responses) == [200, 409]
        expected_stock = 5 if responses[0].status_code == 200 else 3
    assert (await client.get(f"/api/v1/products/{product_id}")).json()["stock"] == expected_stock


async def test_cancel_duplicate_items(client, auth_headers, admin_headers):
    product = await client.post(
        "/api/v1/products",
        headers=admin_headers,
        json={
            "sku": "repeat-items",
            "name": "Test",
            "price": 10,
            "stock": 5,
        },
    )
    product_id = product.json()["id"]
    order = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [
                {"product_id": product_id, "quantity": 1},
                {"product_id": product_id, "quantity": 2},
            ]
        },
    )
    assert order.status_code == 201
    response = await client.patch(
        f"/api/v1/orders/{order.json()['id']}/status",
        params={"new_status": "cancelled"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert (await client.get(f"/api/v1/products/{product_id}")).json()["stock"] == 5
