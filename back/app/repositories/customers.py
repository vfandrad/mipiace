"""Acesso a dados de clientes e endereços."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Address, Customer


async def get_customer_by_phone(session: AsyncSession, phone: str) -> Customer | None:
    return await session.scalar(select(Customer).where(Customer.phone == phone))


async def get_customer(session: AsyncSession, customer_id: UUID) -> Customer | None:
    return await session.get(Customer, customer_id)


async def create_customer(
    session: AsyncSession, *, phone: str, name: str | None = None
) -> Customer:
    customer = Customer(phone=phone, name=name)
    session.add(customer)
    await session.flush()
    return customer


async def list_addresses(session: AsyncSession, customer_id: UUID) -> list[Address]:
    result = await session.scalars(
        select(Address)
        .where(Address.customer_id == customer_id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
    )
    return list(result)


async def get_default_address(
    session: AsyncSession, customer_id: UUID
) -> Address | None:
    addresses = await list_addresses(session, customer_id)
    return addresses[0] if addresses else None


async def create_address(
    session: AsyncSession, *, customer_id: UUID, data: dict[str, Any]
) -> Address:
    address = Address(customer_id=customer_id, **data)
    session.add(address)
    await session.flush()
    return address


__all__ = [
    "create_address",
    "create_customer",
    "get_customer",
    "get_customer_by_phone",
    "get_default_address",
    "list_addresses",
]
