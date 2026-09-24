"""Carrinho em construção durante a conversa — e a conta dele.

Vive serializado no campo JSONB `conversations.cart` e é convertido em
order_items no momento em que o pedido é fechado.

**A conta mora aqui, e é uma só.** Antes havia duas: estas propriedades somavam
`Decimal` cru e eram o que o cliente via e confirmava no WhatsApp, enquanto
`services/pricing.py` arredondava unidade por unidade e era o que virava pedido
e cobrança. Com `numeric(10, 2)` no banco os dois resultados batiam, então
ninguém foi cobrado errado — mas duas implementações da mesma conta é
exatamente a divergência que o `pricing` dizia existir para evitar. Agora o
`pricing` cuida do que depende de configuração (taxa de entrega, o resumo em
`PriceBreakdown`) e chama esta conta; nem o LLM, nem o front, nem o payload do
WhatsApp decidem valor.

A regra do arredondamento: **arredonda o unitário antes de multiplicar**. É
assim que o cliente confere ("2 x R$ 24,90 = R$ 49,80") e é o que evita
diferença de centavo entre o que foi dito no WhatsApp e o que foi gravado.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from pydantic import BaseModel, Field

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | int | float | str) -> Decimal:
    """Normaliza qualquer valor monetário para 2 casas (ROUND_HALF_UP).

    ROUND_HALF_UP é o arredondamento comercial esperado no Brasil — e não o
    `ROUND_HALF_EVEN` que o Python usa por padrão.
    """
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def complements_total(extras: Iterable[Decimal]) -> Decimal:
    """Soma dos adicionais de UMA unidade do item."""
    return money(sum(extras, ZERO))


def item_unit_price(base_price: Decimal, extras: Iterable[Decimal] = ()) -> Decimal:
    """Preço de uma unidade: base + complementos escolhidos."""
    return money(money(base_price) + complements_total(extras))


class CartComplement(BaseModel):
    id: UUID
    group_id: UUID
    name: str
    extra_price: Decimal = Decimal("0")


class CartItem(BaseModel):
    product_id: UUID
    product_name: str
    unit_base_price: Decimal
    quantity: int = 1
    complements: list[CartComplement] = Field(default_factory=list)
    details: str | None = None

    @property
    def unit_price(self) -> Decimal:
        """Preço de uma unidade já com os complementos escolhidos."""
        return item_unit_price(
            self.unit_base_price, (c.extra_price for c in self.complements)
        )

    @property
    def line_total(self) -> Decimal:
        """Total da linha: (base + adicionais) * quantidade."""
        if self.quantity < 1:
            raise ValueError("quantidade precisa ser >= 1")
        return money(self.unit_price * self.quantity)


class Cart(BaseModel):
    items: list[CartItem] = Field(default_factory=list)

    @property
    def subtotal(self) -> Decimal:
        return money(sum((item.line_total for item in self.items), ZERO))

    @property
    def is_empty(self) -> bool:
        return not self.items

    def total(self, delivery_fee: Decimal = ZERO) -> Decimal:
        return money(self.subtotal + money(delivery_fee))
