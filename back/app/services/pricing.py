"""Preço do pedido fechado: o que depende de configuração da loja.

A conta do carrinho (arredondamento, unitário, total da linha, subtotal) mora
em `app/domain/cart.py`, junto do dado que ela soma — e é única. Aqui fica só o
que o domínio não sabe sozinho porque depende de `settings`: a taxa de entrega
e o resumo em três números que vira coluna de `orders`.

Antes este módulo reimplementava a conta inteira, em paralelo com as
propriedades do `Cart`. Eram duas verdades para o mesmo valor.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.core.config import get_settings
from app.domain.cart import ZERO, Cart, money
from app.domain.enums import FulfillmentType
from app.schemas.common import Money


class PriceBreakdown(BaseModel):
    """Resultado do cálculo, pronto para virar colunas de `orders`."""

    subtotal: Money
    delivery_fee: Money
    total: Money


def delivery_fee_for(
    fulfillment_type: FulfillmentType, *, fee: Decimal | None = None
) -> Decimal:
    """Retirada na loja não paga entrega; entrega usa a taxa de `settings`."""
    if fulfillment_type is FulfillmentType.RETIRADA:
        return ZERO
    return money(get_settings().delivery_fee if fee is None else fee)


def calculate_cart(
    cart: Cart,
    *,
    fulfillment_type: FulfillmentType = FulfillmentType.ENTREGA,
    delivery_fee: Decimal | None = None,
) -> PriceBreakdown:
    """Subtotal + taxa de entrega + total de um carrinho."""
    subtotal = cart.subtotal
    fee = delivery_fee_for(fulfillment_type, fee=delivery_fee)
    return PriceBreakdown(subtotal=subtotal, delivery_fee=fee, total=money(subtotal + fee))


__all__ = ["PriceBreakdown", "calculate_cart", "delivery_fee_for"]
