from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models import Order, OrderStatus, User
from app.schemas import OrderCreate, OrderRead
from app.services import orders as orders_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Order:
    return await orders_service.create_order(session, user.id, payload)


@router.get("", response_model=list[OrderRead])
async def list_orders(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Order]:
    return await orders_service.list_orders(session, user.id, is_admin=user.is_admin)


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: int = Path(ge=1, le=2_147_483_647),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Order:
    return await orders_service.get_order(session, user.id, order_id, is_admin=user.is_admin)


@router.patch("/{order_id}/status", response_model=OrderRead)
async def change_status(
    new_status: OrderStatus,
    order_id: int = Path(ge=1, le=2_147_483_647),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Order:
    return await orders_service.change_order_status(
        session, user.id, order_id, new_status, is_admin=user.is_admin
    )
