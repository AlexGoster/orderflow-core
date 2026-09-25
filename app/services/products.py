from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Product
from app.schemas import ProductCreate


async def list_products(
    session: AsyncSession, *, offset: int = 0, limit: int = 50
) -> list[Product]:
    result = await session.scalars(select(Product).order_by(Product.id).offset(offset).limit(limit))
    return list(result)


async def get_product(session: AsyncSession, product_id: int) -> Product:
    product = await session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found")
    return product


async def create_product(session: AsyncSession, payload: ProductCreate) -> Product:
    existing = await session.scalar(select(Product).where(Product.sku == payload.sku))
    if existing is not None:
        raise ConflictError(f"SKU {payload.sku} already exists")
    product = Product(**payload.model_dump())
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product
