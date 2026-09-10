"""Cálculo de preço — a única fonte de verdade de valor no sistema.

Nem o LLM, nem o front, nem o payload do WhatsApp decidem quanto custa: tudo
passa por aqui, sempre em `Decimal` e sempre arredondado uma única vez, no fim
de cada etapa (ROUND_HALF_UP, que é o arredondamento comercial esperado).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.core.config import get_settings
from app.domain.cart import Cart, CartItem
from app.domain.enums import FulfillmentType
from app.schemas.common import Money

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | int | str) -> Decimal:
    """Normaliza qualquer valor monetário para 2 casas."""
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


class PriceBreakdown(BaseModel):
    """Resultado do cálculo, pronto para virar colunas de `orders`."""

    subtotal: Money
    delivery_fee: Money
    total: Money


def complements_total(extras: Iterable[Decimal]) -> Decimal:
    """Soma dos adicionais de UMA unidade do item."""
    return money(sum(extras, ZERO))


def item_unit_price(base_price: Decimal, extras: Iterable[Decimal] = ()) -> Decimal:
    """Preço de uma unidade: base + complementos escolhidos."""
    return money(money(base_price) + complements_total(extras))


def item_line_total(item: CartItem) -> Decimal:
    """Total da linha: (base + adicionais) * quantidade.

    Arredonda o unitário antes de multiplicar — é assim que o cliente confere a
    conta ("2 x R$ 24,90 = R$ 49,80") e é o que evita divergência de centavo
    entre o que foi dito no WhatsApp e o que foi gravado no pedido.
    """
    if item.quantity < 1:
        raise ValueError("quantidade precisa ser >= 1")
    unit = item_unit_price(
        item.unit_base_price, (c.extra_price for c in item.complements)
    )
    return money(unit * item.quantity)


def cart_subtotal(cart: Cart) -> Decimal:
    return money(sum((item_line_total(item) for item in cart.items), ZERO))


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
    subtotal = cart_subtotal(cart)
    fee = delivery_fee_for(fulfillment_type, fee=delivery_fee)
    return PriceBreakdown(subtotal=subtotal, delivery_fee=fee, total=money(subtotal + fee))


def format_brl(value: Decimal) -> str:
    """"R$ 24,90" — usado nas mensagens que o agente manda pro cliente."""
    text = f"{money(value):,.2f}"
    return "R$ " + text.replace(",", "_").replace(".", ",").replace("_", ".")


__all__ = [
    "PriceBreakdown",
    "calculate_cart",
    "cart_subtotal",
    "complements_total",
    "delivery_fee_for",
    "format_brl",
    "item_line_total",
    "item_unit_price",
    "money",
]
