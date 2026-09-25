from httpx import AsyncClient

PRODUCT = {"sku": "SKU-100", "name": "Desk Lamp", "price": 1500.0, "stock": 5}


async def _create_product(client: AsyncClient) -> int:
    resp = await client.post("/api/v1/products", json=PRODUCT)
    return resp.json()["id"]


async def test_create_order_and_decrement_stock(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product_id = await _create_product(client)

    resp = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product_id, "quantity": 2}]},
    )
    assert resp.status_code == 201
    order = resp.json()
    assert order["total"] == 3000.0
    assert order["status"] == "pending"

    stock = await client.get(f"/api/v1/products/{product_id}")
    assert stock.json()["stock"] == 3


async def test_order_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/orders", json={"items": []})
    assert resp.status_code in (401, 422)


async def test_insufficient_stock(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    product_id = await _create_product(client)
    resp = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product_id, "quantity": 999}]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "insufficient_stock"


async def test_list_and_get_order(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    product_id = await _create_product(client)
    created = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product_id, "quantity": 1}]},
    )
    order_id = created.json()["id"]

    assert (await client.get("/api/v1/orders", headers=auth_headers)).status_code == 200
    got = await client.get(f"/api/v1/orders/{order_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["id"] == order_id


async def test_cannot_read_foreign_order(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    product_id = await _create_product(client)
    created = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product_id, "quantity": 1}]},
    )
    order_id = created.json()["id"]

    await client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "secret-pass-2"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": "other@example.com", "password": "secret-pass-2"}
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"/api/v1/orders/{order_id}", headers=other_headers)
    assert resp.status_code == 404
