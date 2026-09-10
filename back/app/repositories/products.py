"""Acesso a dados do catálogo.

Repositório fino de propósito: quem tem regra é o service; aqui só mora SQL.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Complement, ComplementGroup, FlavorCategory, Product


async def list_products(
    session: AsyncSession, *, only_available: bool = False
) -> list[Product]:
    """Produtos com grupos e complementos (carregados via selectin no model)."""
    stmt = select(Product).order_by(Product.sort_order, Product.name)
    if only_available:
        stmt = stmt.where(Product.is_available.is_(True))
    result = await session.scalars(stmt)
    return list(result)


async def get_product(session: AsyncSession, product_id: UUID) -> Product | None:
    return await session.get(Product, product_id)


async def create_product(session: AsyncSession, data: dict[str, Any]) -> Product:
    product = Product(**data)
    session.add(product)
    await session.flush()
    await session.refresh(product)
    return product


async def update_product(
    session: AsyncSession, product: Product, data: dict[str, Any]
) -> Product:
    for field, value in data.items():
        setattr(product, field, value)
    await session.flush()
    return product


async def delete_product(session: AsyncSession, product: Product) -> None:
    await session.delete(product)
    await session.flush()


# --- Grupos ------------------------------------------------------------------


async def get_group(session: AsyncSession, group_id: UUID) -> ComplementGroup | None:
    return await session.get(ComplementGroup, group_id)


async def create_group(
    session: AsyncSession, *, product_id: UUID, data: dict[str, Any]
) -> ComplementGroup:
    group = ComplementGroup(product_id=product_id, **data)
    session.add(group)
    await session.flush()
    await session.refresh(group)
    return group


async def update_group(
    session: AsyncSession, group: ComplementGroup, data: dict[str, Any]
) -> ComplementGroup:
    for field, value in data.items():
        setattr(group, field, value)
    await session.flush()
    return group


async def delete_group(session: AsyncSession, group: ComplementGroup) -> None:
    await session.delete(group)
    await session.flush()


# --- Complementos ------------------------------------------------------------


async def get_complement(
    session: AsyncSession, complement_id: UUID
) -> Complement | None:
    return await session.get(Complement, complement_id)


async def create_complement(
    session: AsyncSession, *, group_id: UUID, data: dict[str, Any]
) -> Complement:
    complement = Complement(group_id=group_id, **data)
    session.add(complement)
    await session.flush()
    await session.refresh(complement)
    return complement


async def update_complement(
    session: AsyncSession, complement: Complement, data: dict[str, Any]
) -> Complement:
    for field, value in data.items():
        setattr(complement, field, value)
    await session.flush()
    return complement


async def delete_complement(session: AsyncSession, complement: Complement) -> None:
    await session.delete(complement)
    await session.flush()


async def list_flavor_categories(session: AsyncSession) -> list[FlavorCategory]:
    stmt = select(FlavorCategory).order_by(
        FlavorCategory.sort_order, FlavorCategory.name
    )
    result = await session.scalars(stmt)
    return list(result)


__all__ = [
    "create_complement",
    "create_group",
    "create_product",
    "delete_complement",
    "delete_group",
    "delete_product",
    "get_complement",
    "get_group",
    "get_product",
    "list_flavor_categories",
    "list_products",
    "update_complement",
    "update_group",
    "update_product",
]
