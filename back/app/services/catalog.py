"""O cardápio: CRUD do painel e o snapshot que o agente enxerga.

Duas leituras do mesmo dado, por isso moram juntas:

* O painel (`/api/products`) cria, edita e desativa produtos, grupos e
  complementos. É o CRUD que o lojista usa todo dia, porque os sabores mudam.
* O agente pede `get_catalog_snapshot()` — a árvore inteira em objetos de
  domínio. É esse snapshot que serve de "grounding": o resolvedor só aceita
  produto ou sabor que exista aqui dentro.

Este módulo é quem fala com o banco. As rotas não tocam no SQLAlchemy e são
elas que decidem a transação (`await session.commit()`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Complement, ComplementGroup, FlavorCategory, Product
from app.domain.catalog import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
)

#: Tudo que o CRUD do cardápio edita. Criar/editar/apagar é igual para os três,
#: então as funções genéricas abaixo servem a todos.
CatalogRow = Product | ComplementGroup | Complement


# ---------------------------------------------------------------------------
# Operações comuns aos três níveis (produto > grupo > complemento)
# ---------------------------------------------------------------------------

async def update_item[T: CatalogRow](session: AsyncSession, item: T, data: dict[str, Any]) -> T:
    """Aplica os campos enviados no PATCH. `data` já vem validado pelo schema."""
    for field, value in data.items():
        setattr(item, field, value)
    await session.flush()
    return item


async def delete_item(session: AsyncSession, item: CatalogRow) -> None:
    await session.delete(item)
    await session.flush()


async def _add(session: AsyncSession, item: CatalogRow) -> Any:
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------

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
    return await _add(session, Product(**data))


# ---------------------------------------------------------------------------
# Grupos de complementos
# ---------------------------------------------------------------------------

async def get_group(session: AsyncSession, group_id: UUID) -> ComplementGroup | None:
    return await session.get(ComplementGroup, group_id)


async def create_group(
    session: AsyncSession, *, product_id: UUID, data: dict[str, Any]
) -> ComplementGroup:
    return await _add(session, ComplementGroup(product_id=product_id, **data))


# ---------------------------------------------------------------------------
# Complementos (os sabores)
# ---------------------------------------------------------------------------

async def get_complement(
    session: AsyncSession, complement_id: UUID
) -> Complement | None:
    return await session.get(Complement, complement_id)


async def create_complement(
    session: AsyncSession, *, group_id: UUID, data: dict[str, Any]
) -> Complement:
    return await _add(session, Complement(group_id=group_id, **data))


async def list_flavor_categories(session: AsyncSession) -> list[FlavorCategory]:
    stmt = select(FlavorCategory).order_by(
        FlavorCategory.sort_order, FlavorCategory.name
    )
    result = await session.scalars(stmt)
    return list(result)


# ---------------------------------------------------------------------------
# O cardápio como o agente enxerga
# ---------------------------------------------------------------------------

async def get_catalog_snapshot(session: AsyncSession) -> CatalogSnapshot:
    """Cardápio inteiro em árvore produto → grupos → complementos.

    Traz também os indisponíveis (com `is_available=False`): quem filtra é o
    consumidor, e o agente precisa saber que o sabor existe mas acabou para
    responder "hoje não tem pistache" em vez de "não entendi".
    """
    rows = await list_products(session)
    return CatalogSnapshot(
        products=[
            CatalogProduct(
                id=product.id,
                name=product.name,
                description=product.description,
                base_price=product.base_price,
                is_available=product.is_available,
                groups=[
                    CatalogGroup(
                        id=group.id,
                        product_id=group.product_id,
                        name=group.name,
                        min_choices=group.min_choices,
                        max_choices=group.max_choices,
                        is_required=group.is_required,
                        complements=[
                            CatalogComplement(
                                id=complement.id,
                                group_id=complement.group_id,
                                name=complement.name,
                                extra_price=complement.extra_price,
                                is_available=complement.is_available,
                            )
                            for complement in group.complements
                        ],
                    )
                    for group in product.groups
                ],
            )
            for product in rows
        ]
    )
