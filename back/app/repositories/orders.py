"""Acesso a dados de pedidos."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, order_code_seq
from app.domain.enums import OrderStatus


async def list_orders(
    session: AsyncSession,
    *,
    status: OrderStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Order]:
    """Lista para o Kanban: mais recentes primeiro, com itens e pagamentos."""
    stmt = select(Order).order_by(Order.created_at.desc()).limit(limit).offset(offset)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    result = await session.scalars(stmt)
    return list(result)


async def get_order(session: AsyncSession, order_id: UUID) -> Order | None:
    return await session.get(Order, order_id)


async def get_order_by_code(session: AsyncSession, code: str) -> Order | None:
    return await session.scalar(select(Order).where(Order.code == code))


async def next_code_number(session: AsyncSession) -> int:
    """`nextval('order_code_seq')` — números sem colisão mesmo em concorrência."""
    value = await session.scalar(select(order_code_seq.next_value()))
    return int(value)


__all__ = ["get_order", "get_order_by_code", "list_orders", "next_code_number"]
