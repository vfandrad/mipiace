"""Preço é a regra que não pode errar — é ela que o cliente confere no WhatsApp."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.cart import Cart, CartComplement, CartItem
from app.domain.enums import FulfillmentType
from app.services import pricing


def _complement(name: str, extra: str) -> CartComplement:
    return CartComplement(
        id=uuid4(), group_id=uuid4(), name=name, extra_price=Decimal(extra)
    )


def _pote_500() -> CartItem:
    """Pote 500ml com 3 sabores, dois deles com adicional."""
    return CartItem(
        product_id=uuid4(),
        product_name="Pote 500ml",
        unit_base_price=Decimal("39.90"),
        quantity=1,
        complements=[
            _complement("Pistache", "4.00"),
            _complement("Nutella", "3.00"),
            _complement("Morango", "0.00"),
        ],
    )


def test_money_quantiza_para_centavos():
    assert pricing.money(Decimal("10.005")) == Decimal("10.01")  # meio pra cima
    assert pricing.money(Decimal("10")) == Decimal("10.00")


def test_unit_price_soma_complementos():
    item = _pote_500()
    assert pricing.item_unit_price(
        item.unit_base_price, [c.extra_price for c in item.complements]
    ) == Decimal("46.90")


def test_line_total_multiplica_pela_quantidade():
    item = _pote_500()
    item.quantity = 3
    assert pricing.item_line_total(item) == Decimal("140.70")


def test_line_total_rejeita_quantidade_invalida():
    item = _pote_500()
    item.quantity = 0
    with pytest.raises(ValueError):
        pricing.item_line_total(item)


def test_item_sem_complemento_usa_so_o_preco_base():
    item = CartItem(
        product_id=uuid4(),
        product_name="Casquinha",
        unit_base_price=Decimal("12.00"),
        quantity=2,
    )
    assert pricing.item_line_total(item) == Decimal("24.00")


def test_carrinho_com_entrega():
    cart = Cart(
        items=[
            _pote_500(),  # 46,90
            CartItem(
                product_id=uuid4(),
                product_name="Casquinha",
                unit_base_price=Decimal("12.00"),
                quantity=2,
            ),  # 24,00
        ]
    )
    breakdown = pricing.calculate_cart(
        cart, fulfillment_type=FulfillmentType.ENTREGA, delivery_fee=Decimal("5.00")
    )
    assert breakdown.subtotal == Decimal("70.90")
    assert breakdown.delivery_fee == Decimal("5.00")
    assert breakdown.total == Decimal("75.90")


def test_retirada_nao_cobra_entrega():
    cart = Cart(items=[_pote_500()])
    breakdown = pricing.calculate_cart(
        cart, fulfillment_type=FulfillmentType.RETIRADA, delivery_fee=Decimal("9.99")
    )
    assert breakdown.delivery_fee == Decimal("0.00")
    assert breakdown.total == breakdown.subtotal == Decimal("46.90")


def test_carrinho_vazio_soma_zero():
    breakdown = pricing.calculate_cart(
        Cart(), fulfillment_type=FulfillmentType.RETIRADA
    )
    assert breakdown.subtotal == Decimal("0.00")
    assert breakdown.total == Decimal("0.00")


def test_tudo_continua_decimal():
    breakdown = pricing.calculate_cart(Cart(items=[_pote_500()]))
    assert isinstance(breakdown.subtotal, Decimal)
    assert isinstance(breakdown.total, Decimal)

