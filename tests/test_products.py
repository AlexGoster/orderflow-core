from httpx import AsyncClient

PRODUCT = {"sku": "SKU-1", "name": "Mechanical Keyboard", "price": 4990.0, "stock": 10}


async def test_product_crud(client: AsyncClient) -> None:
    created = await client.post("/api/v1/products", json=PRODUCT)
    assert created.status_code == 201
    product_id = created.json()["id"]

    listed = await client.get("/api/v1/products")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = await client.get(f"/api/v1/products/{product_id}")
    assert fetched.status_code == 200
    assert fetched.json()["sku"] == "SKU-1"


async def test_duplicate_sku_rejected(client: AsyncClient) -> None:
    await client.post("/api/v1/products", json=PRODUCT)
    dup = await client.post("/api/v1/products", json=PRODUCT)
    assert dup.status_code == 409


async def test_product_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/products/999")
    assert resp.status_code == 404
