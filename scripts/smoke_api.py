"""Exercise a running API with disposable data; use only a dedicated test database."""

import argparse
import asyncio
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.cli import create_admin
from app.core.config import get_settings
from app.core.database import dispose_engine, get_session_factory
from app.models import Order, Product


async def main(base_url: str) -> None:
    from sqlalchemy.engine import make_url

    if not (make_url(get_settings().database_url).database or "").endswith("_test"):
        raise ValueError("DATABASE_URL must point to a dedicated database ending in _test")
    suffix = uuid4().hex
    admin_email = f"smoke-admin-{suffix}@example.com"
    await create_admin(admin_email, "local-test-password")
    async with httpx.AsyncClient(base_url=base_url, trust_env=False) as client:

        async def request(method, path, expected=200, **kwargs):
            response = await client.request(method, path, **kwargs)
            assert response.status_code == expected, (method, path, response.status_code)
            return response.json()

        await request("GET", "/health")
        await request("GET", "/openapi.json")
        payload = {"email": f"smoke-{suffix}@example.com", "password": "local-test-password"}
        await request("POST", "/api/v1/auth/register", 201, json=payload)
        await request("POST", "/api/v1/auth/register", 409, json=payload)
        token = await request("POST", "/api/v1/auth/login", json=payload)
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        admin_token = await request(
            "POST",
            "/api/v1/auth/login",
            json={
                "email": admin_email,
                "password": "local-test-password",
            },
        )
        admin_headers = {"Authorization": f"Bearer {admin_token['access_token']}"}
        await request("GET", "/api/v1/auth/me", headers=headers)
        await request("GET", "/api/v1/auth/me", 401)
        await request(
            "POST", "/api/v1/auth/login", 401, json={**payload, "password": "wrong-password"}
        )
        product = await request(
            "POST",
            "/api/v1/products",
            201,
            headers=admin_headers,
            json={
                "sku": suffix,
                "name": "Smoke test",
                "price": "12.34",
                "stock": 2,
            },
        )
        body = {"items": [{"product_id": product["id"], "quantity": 2}]}
        await request(
            "POST",
            "/api/v1/products",
            403,
            headers=headers,
            json={
                "sku": f"denied-{suffix}",
                "name": "Test",
                "price": 10,
            },
        )
        order = await request("POST", "/api/v1/orders", 201, headers=headers, json=body)
        assert order["total"] == 24.68
        await request("GET", f"/api/v1/orders/{order['id']}", headers=headers)
        await request(
            "PATCH", f"/api/v1/orders/{order['id']}/status?new_status=paid", 403, headers=headers
        )
        await request(
            "PATCH", f"/api/v1/orders/{order['id']}/status?new_status=paid", headers=admin_headers
        )
        await request("POST", "/api/v1/orders", 409, headers=headers, json=body)
        assert (await request("GET", f"/api/v1/products/{product['id']}"))["stock"] == 0
        assert len(await request("GET", "/api/v1/orders", headers=headers)) == 1
        for _ in range(2):
            await request(
                "PATCH",
                f"/api/v1/orders/{order['id']}/status?new_status=cancelled",
                headers=admin_headers,
            )
            assert (await request("GET", f"/api/v1/products/{product['id']}"))["stock"] == 2
        await request("POST", "/api/v1/orders", 422, headers=headers, json={"items": []})
        await request("GET", "/api/v1/orders/2147483647", 404, headers=headers)
    async with get_session_factory()() as session:
        saved = await session.scalar(select(Order).where(Order.id == order["id"]))
        stock = await session.scalar(select(Product.stock).where(Product.id == product["id"]))
        assert saved is not None and str(saved.total) == "24.68" and saved.status == "cancelled"
        assert len(saved.items) == 1 and stock == 2
    await dispose_engine()
    print("HTTP smoke passed; order, status, items, total and stock verified in database.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    asyncio.run(main(parser.parse_args().base_url))
