"""Snapshot imutável do cardápio.

Este é o "grounding" do agente: o LLM nunca inventa produto, sabor ou preço —
ele devolve texto livre e o resolvedor casa esse texto contra este snapshot.
Se não casar, o agente pede para o cliente repetir em vez de seguir com um
item inexistente.
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


def normalize(text: str) -> str:
    """Minúsculas, sem acento e sem espaço sobrando — para casar nomes."""
    stripped = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in stripped if not unicodedata.combining(ch))


class CatalogComplement(BaseModel):
    id: UUID
    group_id: UUID
    name: str
    extra_price: Decimal = Decimal("0")
    is_available: bool = True


class CatalogGroup(BaseModel):
    id: UUID
    product_id: UUID
    name: str
    min_choices: int = 0
    max_choices: int = 1
    is_required: bool = False
    complements: list[CatalogComplement] = Field(default_factory=list)

    @property
    def available_complements(self) -> list[CatalogComplement]:
        return [c for c in self.complements if c.is_available]


class CatalogProduct(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    base_price: Decimal
    is_available: bool = True
    groups: list[CatalogGroup] = Field(default_factory=list)

    @property
    def required_groups(self) -> list[CatalogGroup]:
        return [g for g in self.groups if g.is_required or g.min_choices > 0]


class CatalogSnapshot(BaseModel):
    """O cardápio inteiro, já montado em árvore, como o agente enxerga."""

    products: list[CatalogProduct] = Field(default_factory=list)

    @property
    def available_products(self) -> list[CatalogProduct]:
        return [p for p in self.products if p.is_available]

    def product_by_id(self, product_id: UUID) -> CatalogProduct | None:
        return next((p for p in self.products if p.id == product_id), None)

    def group_by_id(self, group_id: UUID) -> CatalogGroup | None:
        for product in self.products:
            for group in product.groups:
                if group.id == group_id:
                    return group
        return None

    def complement_by_id(self, complement_id: UUID) -> CatalogComplement | None:
        for product in self.products:
            for group in product.groups:
                for complement in group.complements:
                    if complement.id == complement_id:
                        return complement
        return None
