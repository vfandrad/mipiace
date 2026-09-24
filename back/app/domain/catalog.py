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
    #: "Sem lactose" / "Com lactose" — é o que deixa o cardápio sair agrupado
    #: numa mensagem só em vez de 31 linhas soltas.
    category: str | None = None
    id: UUID
    group_id: UUID
    name: str
    extra_price: Decimal = Decimal("0")
    is_available: bool = True


class CatalogGroup(BaseModel):
    """Um grupo de escolhas JÁ RESOLVIDO para um produto.

    `id` é o id do grupo compartilhado (`complement_groups`), e é ele que casa
    com o `group_id` dos complementos no carrinho. `min_choices`/`max_choices`
    vêm do vínculo daquele produto, porque a mesma lista de sabores pode pedir
    2 escolhas num pote e 6 no combo. O snapshot é desnormalizado de propósito:
    o agente lê "este produto tem estes grupos com estas regras" e não precisa
    saber que existe uma tabela de vínculo.
    """

    id: UUID
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

    def product_by_name(self, name: str) -> CatalogProduct | None:
        """Produto cujo nome é exatamente `name` (ignorando acento e caixa).

        É por aqui que passa o nome de cardápio devolvido pelo LLM: ou ele
        existe de verdade, ou é descartado. Nome parecido não serve — para
        texto livre do cliente existe o `resolver`.
        """
        wanted = normalize(name)
        return next((p for p in self.products if normalize(p.name) == wanted), None)
