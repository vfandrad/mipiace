"""Montagem do cardápio em árvore.

`get_catalog_snapshot` é o contrato com o agente de WhatsApp: é este snapshot
que serve de "grounding" — o resolvedor só aceita produto/sabor que exista
aqui dentro.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.catalog import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
)
from app.repositories import products as products_repo


async def get_catalog_snapshot(session: AsyncSession) -> CatalogSnapshot:
    """Cardápio inteiro em árvore produto → grupos → complementos.

    Traz também os indisponíveis (com `is_available=False`): quem filtra é o
    consumidor, e o agente precisa saber que o sabor existe mas acabou para
    responder "hoje não tem pistache" em vez de "não entendi".
    """
    rows = await products_repo.list_products(session)
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


__all__ = ["get_catalog_snapshot"]
