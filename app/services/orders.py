from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models import Order, OrderItem, OrderStatus, Product
from app.schemas import OrderCreate


async def create_order(session: AsyncSession, user_id: int, payload: OrderCreate) -> Order:
    order = Order(user_id=user_id, total=Decimal("0"))
    session.add(order)
    await session.flush()

    total = Decimal("0")
    for item in payload.items:
        product = await session.get(Product, item.product_id)
        if product is None:
            raise NotFoundError(f"Product {item.product_id} not found")
        if product.stock < item.quantity:
            raise AppError(
                f"Insufficient stock for {product.sku}: {product.stock} left",
                code="insufficient_stock",
                status_code=409,
            )
        product.stock -= item.quantity
        total += Decimal(str(product.price)) * item.quantity
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=item.quantity,
                unit_price=product.price,
            )
        )

    order.total = total
    await session.commit()
    await session.refresh(order)
    return order


async def list_orders(session: AsyncSession, user_id: int) -> list[Order]:
    result = await session.scalars(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
    )
    return list(result)


async def get_order(session: AsyncSession, user_id: int, order_id: int) -> Order:
    order = await session.scalar(select(Order).where(Order.id == order_id))
    if order is None or order.user_id != user_id:
        raise NotFoundError("Order not found")
    return order


async def change_order_status(session: AsyncSession, order_id: int, status: OrderStatus) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    order.status = status
    await session.commit()
    await session.refresh(order)
    return order
