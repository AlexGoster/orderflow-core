from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Product
from app.schemas import ProductCreate, ProductRead
from app.services import products as products_service

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductRead])
async def list_products(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[Product]:
    return await products_service.list_products(session, offset=offset, limit=limit)


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(product_id: int, session: AsyncSession = Depends(get_session)) -> Product:
    return await products_service.get_product(session, product_id)


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate, session: AsyncSession = Depends(get_session)
) -> Product:
    return await products_service.create_product(session, payload)
