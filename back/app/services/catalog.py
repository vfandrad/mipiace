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

from app.db.models import (
    Complement,
    ComplementCategory,
    ComplementGroup,
    Product,
    ProductGroup,
)
from app.domain.catalog import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
)

#: Tudo que o CRUD do cardápio edita. Criar/editar/apagar é igual para os três,
#: então as funções genéricas abaixo servem a todos.
CatalogRow = Product | ComplementGroup | ProductGroup | Complement | ComplementCategory


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
# Grupos de complementos (a biblioteca) e os vínculos com os produtos
# ---------------------------------------------------------------------------

async def list_groups(session: AsyncSession) -> list[ComplementGroup]:
    """A biblioteca de grupos — é dela que o painel oferece "usar este grupo"."""
    stmt = select(ComplementGroup).order_by(
        ComplementGroup.sort_order, ComplementGroup.name
    )
    result = await session.scalars(stmt)
    return list(result)


async def get_group(session: AsyncSession, group_id: UUID) -> ComplementGroup | None:
    return await session.get(ComplementGroup, group_id)


async def create_group(session: AsyncSession, data: dict[str, Any]) -> ComplementGroup:
    """Cria a lista. Ela ainda não pertence a produto nenhum — `link_group` faz isso."""
    return await _add(session, ComplementGroup(**data))


async def get_product_group(
    session: AsyncSession, link_id: UUID
) -> ProductGroup | None:
    return await session.get(ProductGroup, link_id)


async def find_link(
    session: AsyncSession, *, product_id: UUID, group_id: UUID
) -> ProductGroup | None:
    """O vínculo existente entre este produto e este grupo, se houver."""
    stmt = select(ProductGroup).where(
        ProductGroup.product_id == product_id, ProductGroup.group_id == group_id
    )
    return await session.scalar(stmt)


async def link_group(
    session: AsyncSession, *, product_id: UUID, group_id: UUID, data: dict[str, Any]
) -> ProductGroup:
    """Faz o produto usar o grupo, com a regra de escolha DELE.

    Se o vínculo já existe, atualiza a regra em vez de criar um segundo — dois
    vínculos iguais fariam o agente perguntar os sabores duas vezes.
    """
    existente = await find_link(session, product_id=product_id, group_id=group_id)
    if existente is not None:
        return await update_item(session, existente, data)
    return await _add(
        session, ProductGroup(product_id=product_id, group_id=group_id, **data)
    )


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


async def get_category(
    session: AsyncSession, category_id: UUID
) -> ComplementCategory | None:
    return await session.get(ComplementCategory, category_id)


async def create_category(
    session: AsyncSession, data: dict[str, Any]
) -> ComplementCategory:
    return await _add(session, ComplementCategory(**data))


async def list_complement_categories(session: AsyncSession) -> list[ComplementCategory]:
    stmt = select(ComplementCategory).order_by(
        ComplementCategory.sort_order, ComplementCategory.name
    )
    result = await session.scalars(stmt)
    return list(result)


# ---------------------------------------------------------------------------
# Ordem (arrastar e soltar no painel)
# ---------------------------------------------------------------------------

#: Qual tabela cada tipo de item reordenável usa.
_ORDERABLE = {
    "product": Product,
    "group": ComplementGroup,
    # A ordem em que os grupos aparecem DENTRO de um produto é do vínculo.
    "product_group": ProductGroup,
    "complement": Complement,
    "category": ComplementCategory,
}


async def reorder(session: AsyncSession, *, kind: str, ids: list[UUID]) -> int:
    """Grava a ordem em que o lojista arrastou os itens.

    `sort_order` vira a posição na lista — 0, 1, 2... — numa transação só. É
    assim porque a alternativa (um PATCH por item) deixa a lista meio ordenada
    se uma das requisições falhar no meio, e o cardápio sai torto no WhatsApp.

    Ids desconhecidos são ignorados em vez de derrubar a operação: a tela pode
    estar mostrando algo que outra aba acabou de apagar.
    """
    model = _ORDERABLE.get(kind)
    if model is None:
        raise ValueError(f"tipo não ordenável: {kind}")

    encontrados = await session.scalars(select(model).where(model.id.in_(ids)))
    por_id = {item.id: item for item in encontrados}
    mexidos = 0
    for posicao, item_id in enumerate(ids):
        item = por_id.get(item_id)
        if item is None:
            continue
        if item.sort_order != posicao:
            item.sort_order = posicao
            mexidos += 1
    await session.flush()
    return mexidos


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
                # `link` é o vínculo produto<->grupo: dele vem a regra de
                # escolha daquele produto; do `link.group`, a lista de itens.
                groups=[
                    CatalogGroup(
                        id=link.group.id,
                        name=link.group.name,
                        min_choices=link.min_choices,
                        max_choices=link.max_choices,
                        is_required=link.is_required,
                        complements=[
                            CatalogComplement(
                                id=complement.id,
                                group_id=complement.group_id,
                                name=complement.name,
                                extra_price=complement.extra_price,
                                is_available=complement.is_available,
                                category=(
                                    complement.category.name
                                    if complement.category
                                    else None
                                ),
                            )
                            for complement in link.group.complements
                        ],
                    )
                    for link in product.groups
                ],
            )
            for product in rows
        ]
    )
