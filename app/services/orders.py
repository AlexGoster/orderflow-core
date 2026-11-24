from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import Order, OrderItem, OrderStatus, Product
from app.schemas import OrderCreate


async def create_order(session: AsyncSession, user_id: int, payload: OrderCreate) -> Order:
    order = Order(user_id=user_id, total=Decimal("0"))
    session.add(order)
    await session.flush()

    total = Decimal("0")
    for item in sorted(payload.items, key=lambda item: item.product_id):
        product = await session.get(Product, item.product_id)
        if product is None:
            raise NotFoundError(f"Product {item.product_id} not found")
        remaining = await session.scalar(
            update(Product)
            .where(Product.id == item.product_id, Product.stock >= item.quantity)
            .values(stock=Product.stock - item.quantity)
            .returning(Product.stock)
            .execution_options(synchronize_session=False)
        )
        if remaining is None:
            raise AppError(
                f"Insufficient stock for {product.sku}",
                code="insufficient_stock",
                status_code=409,
            )
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
    if total > Decimal("99999999.99"):
        raise AppError(
            "Order total exceeds supported amount", code="invalid_total", status_code=422
        )
    await session.commit()
    await session.refresh(order)
    return order


async def list_orders(
    session: AsyncSession, user_id: int, *, is_admin: bool = False
) -> list[Order]:
    query = select(Order).order_by(Order.created_at.desc())
    if not is_admin:
        query = query.where(Order.user_id == user_id)
    result = await session.scalars(query)
    return list(result)


async def get_order(
    session: AsyncSession, user_id: int, order_id: int, *, is_admin: bool = False
) -> Order:
    order = await session.scalar(
        select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    )
    if order is None or (not is_admin and order.user_id != user_id):
        raise NotFoundError("Order not found")
    return order


async def change_order_status(
    session: AsyncSession,
    user_id: int,
    order_id: int,
    status: OrderStatus,
    *,
    is_admin: bool = False,
) -> Order:
    order = await get_order(session, user_id, order_id, is_admin=is_admin)
    if not is_admin and (
        status != OrderStatus.cancelled
        or order.status not in (OrderStatus.pending, OrderStatus.cancelled)
    ):
        raise ForbiddenError("Customers may only cancel their pending orders")
    if order.status == status:
        return order
    transitions = {
        OrderStatus.pending: {OrderStatus.paid, OrderStatus.cancelled},
        OrderStatus.paid: {OrderStatus.shipped, OrderStatus.cancelled},
        OrderStatus.shipped: set(),
        OrderStatus.cancelled: set(),
    }
    if status not in transitions[order.status]:
        raise ConflictError(f"Cannot change order status from {order.status} to {status}")
    changed = await session.scalar(
        update(Order)
        .where(Order.id == order_id, Order.status == order.status)
        .values(status=status)
        .returning(Order.id)
        .execution_options(synchronize_session=False)
    )
    if changed is None:
        await session.refresh(order)
        if order.status == status:
            return order
        raise ConflictError("Order status changed concurrently; reload and retry")
    if status == OrderStatus.cancelled:
        for item in sorted(order.items, key=lambda item: item.product_id):
            await session.execute(
                update(Product)
                .where(Product.id == item.product_id)
                .values(stock=Product.stock + item.quantity)
                .execution_options(synchronize_session=False)
            )
    await session.commit()
    await session.refresh(order)
    return order
