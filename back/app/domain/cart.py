"""Carrinho em construção durante a conversa.

Vive serializado no campo JSONB `conversations.cart` e é convertido em
order_items no momento em que o pedido é fechado. O cálculo de preço aqui é a
única fonte de verdade: nem o LLM nem o front decidem valor.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


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
        return self.unit_base_price + sum(
            (c.extra_price for c in self.complements), Decimal("0")
        )

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class Cart(BaseModel):
    items: list[CartItem] = Field(default_factory=list)

    @property
    def subtotal(self) -> Decimal:
        return sum((item.line_total for item in self.items), Decimal("0"))

    @property
    def is_empty(self) -> bool:
        return not self.items

    def total(self, delivery_fee: Decimal = Decimal("0")) -> Decimal:
        return self.subtotal + delivery_fee
