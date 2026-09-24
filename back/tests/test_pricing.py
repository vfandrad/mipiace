"""Preço é a regra que não pode errar — é ela que o cliente confere no WhatsApp.

A conta em si mora em `domain/cart.py` (é uma só, e é a que o WhatsApp e o
pedido usam); `services/pricing.py` só acrescenta o que depende de `settings`.
Por isso os testes da conta apontam para o domínio e os da taxa, para o serviço.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.cart import Cart, CartComplement, CartItem, item_unit_price, money
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
    assert money(Decimal("10.005")) == Decimal("10.01")  # meio pra cima
    assert money(Decimal("10")) == Decimal("10.00")


def test_unit_price_soma_complementos():
    item = _pote_500()
    assert item_unit_price(
        item.unit_base_price, [c.extra_price for c in item.complements]
    ) == Decimal("46.90")
    # A propriedade do item tem de dar o mesmo: é a conta que o WhatsApp mostra.
    assert item.unit_price == Decimal("46.90")


def test_line_total_multiplica_pela_quantidade():
    item = _pote_500()
    item.quantity = 3
    assert item.line_total == Decimal("140.70")


def test_line_total_rejeita_quantidade_invalida():
    item = _pote_500()
    item.quantity = 0
    with pytest.raises(ValueError):
        _ = item.line_total


def test_item_sem_complemento_usa_so_o_preco_base():
    item = CartItem(
        product_id=uuid4(),
        product_name="Casquinha",
        unit_base_price=Decimal("12.00"),
        quantity=2,
    )
    assert item.line_total == Decimal("24.00")


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



def test_o_total_do_whatsapp_e_o_total_do_pedido():
    """O resumo que o cliente confirma tem de ser, ao centavo, o que é cobrado.

    Este é o teste que guarda a consolidação: antes havia duas implementações da
    mesma conta — as propriedades do `Cart` (que o `renderer` usa para escrever
    o resumo no WhatsApp) e as funções de `pricing` (que viram as colunas de
    `orders`). Se alguém reintroduzir a segunda, este teste cai.

    O item foi escolhido para expor arredondamento: três unidades de um valor
    cujo terço de centavo se perde se a multiplicação vier antes do arredondamento.
    """
    item = _pote_500()
    item.quantity = 3
    cart = Cart(items=[item])

    breakdown = pricing.calculate_cart(cart, fulfillment_type=FulfillmentType.ENTREGA)

    # O que o renderer escreve na mensagem...
    assert cart.subtotal == breakdown.subtotal
    assert cart.total(breakdown.delivery_fee) == breakdown.total
    # ...e o que a linha do pedido guarda.
    assert sum(i.line_total for i in cart.items) == breakdown.subtotal
