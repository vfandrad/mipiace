"""Transições de status do pedido e guardas do fechamento de carrinho."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from app import servicos as orders_service
from app.dominio import (
    Cart,
    CartItem,
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
    FulfillmentType,
    OrderChannel,
    OrderStatus,
)
from app.esquemas import OrderItemInput

S = OrderStatus


# ---------------------------------------------------------------------------
# Transições do Kanban
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origem", "destino"),
    [
        (S.NOVO, S.PREPARANDO),
        (S.NOVO, S.CANCELADO),
        (S.PREPARANDO, S.ENTREGA),
        (S.PREPARANDO, S.FINALIZADO),   # retirada no balcão
        (S.PREPARANDO, S.CANCELADO),
        (S.ENTREGA, S.FINALIZADO),
        (S.ENTREGA, S.CANCELADO),
    ],
)
def test_transicoes_validas(origem: OrderStatus, destino: OrderStatus):
    assert orders_service.can_transition_order(origem, destino)


@pytest.mark.parametrize(
    ("origem", "destino"),
    [
        (S.NOVO, S.ENTREGA),        # não pode pular a produção
        (S.NOVO, S.FINALIZADO),
        (S.ENTREGA, S.PREPARANDO),  # não volta
        (S.FINALIZADO, S.ENTREGA),
        (S.FINALIZADO, S.CANCELADO),
        (S.CANCELADO, S.PREPARANDO),
    ],
)
def test_transicoes_invalidas(origem: OrderStatus, destino: OrderStatus):
    assert not orders_service.can_transition_order(origem, destino)
    with pytest.raises(orders_service.InvalidStatusTransition):
        orders_service.assert_order_transition(origem, destino)


def test_repetir_o_mesmo_status_e_aceito():
    """O Kanban reenvia o status ao soltar o card na mesma coluna."""
    for status in S:
        assert orders_service.can_transition_order(status, status)


def test_estados_terminais_nao_saem_de_lugar():
    assert orders_service.ORDER_TRANSITIONS[S.FINALIZADO] == set()
    assert orders_service.ORDER_TRANSITIONS[S.CANCELADO] == set()


# ---------------------------------------------------------------------------
# Código curto do pedido
# ---------------------------------------------------------------------------


def test_codigo_do_pedido_tem_formato_curto_e_estavel():
    codigo = orders_service.format_order_code(1)
    assert codigo.startswith("#")
    assert len(codigo) == 5
    assert codigo == orders_service.format_order_code(1)  # determinístico


def test_codigos_nao_colidem_e_nao_expoem_o_contador():
    codigos = {orders_service.format_order_code(n) for n in range(1, 5000)}
    assert len(codigos) == 4999
    assert orders_service.format_order_code(1) != "#0001"


# ---------------------------------------------------------------------------
# Guardas de create_order_from_cart (falham antes de tocar no banco)
# ---------------------------------------------------------------------------


def _cart() -> Cart:
    return Cart(
        items=[
            CartItem(
                product_id=uuid4(),
                product_name="Pote 240ml",
                unit_base_price=Decimal("22.90"),
                quantity=1,
            )
        ]
    )


def test_carrinho_vazio_nao_vira_pedido():
    with pytest.raises(orders_service.EmptyCartError):
        asyncio.run(
            orders_service.create_order_from_cart(
                None,  # type: ignore[arg-type]
                cart=Cart(),
                phone="5511990000001",
                customer_name="Ana",
                fulfillment_type=FulfillmentType.ENTREGA,
                address={"rua": "Rua X", "numero": "1", "bairro": "Centro"},
                channel=OrderChannel.WHATSAPP,
            )
        )


def test_entrega_sem_endereco_completo_e_recusada(monkeypatch):
    """Sem rua/número/bairro o pedido não pode nascer — o entregador some."""

    async def _fake_customer(session, *, phone, name=None):
        return type("C", (), {"id": uuid4()})()

    monkeypatch.setattr(orders_service, "get_or_create_customer", _fake_customer)

    with pytest.raises(orders_service.MissingAddressError):
        asyncio.run(
            orders_service.create_order_from_cart(
                None,  # type: ignore[arg-type]
                cart=_cart(),
                phone="5511990000001",
                customer_name="Ana",
                fulfillment_type=FulfillmentType.ENTREGA,
                address={"rua": "Rua X"},  # faltam número e bairro
                channel=OrderChannel.WHATSAPP,
            )
        )


# ---------------------------------------------------------------------------
# Lançamento manual (painel) — fallback com o agente fora do ar
# ---------------------------------------------------------------------------


def _catalogo_para_lancamento_manual() -> CatalogSnapshot:
    group_id = uuid4()
    disponivel_id, esgotado_id = uuid4(), uuid4()
    produto = CatalogProduct(
        id=uuid4(),
        name="Pote 500ml",
        base_price=Decimal("32.00"),
        groups=[
            CatalogGroup(
                id=group_id,
                name="Sabores",
                min_choices=1,
                max_choices=2,
                is_required=True,
                complements=[
                    CatalogComplement(id=disponivel_id, group_id=group_id, name="Pistache"),
                    CatalogComplement(
                        id=esgotado_id, group_id=group_id, name="Maracujá", is_available=False
                    ),
                ],
            )
        ],
    )
    indisponivel = CatalogProduct(
        id=uuid4(), name="Milkshake", base_price=Decimal("22.00"), is_available=False
    )
    return CatalogSnapshot(products=[produto, indisponivel])


def test_lancamento_manual_monta_item_com_preco_do_catalogo() -> None:
    """O painel manda só o id — nome e preço vêm do catálogo, nunca do navegador."""
    catalogo = _catalogo_para_lancamento_manual()
    produto = catalogo.products[0]
    sabor = produto.groups[0].complements[0]

    item = orders_service._cart_item_from_input(
        catalogo,
        OrderItemInput(product_id=produto.id, quantity=2, complement_ids=[sabor.id]),
    )

    assert item.product_name == "Pote 500ml"
    assert item.unit_base_price == Decimal("32.00")
    assert item.quantity == 2
    assert [c.name for c in item.complements] == ["Pistache"]


def test_lancamento_manual_recusa_produto_inexistente_ou_indisponivel() -> None:
    catalogo = _catalogo_para_lancamento_manual()
    indisponivel = catalogo.products[1]

    with pytest.raises(orders_service.InvalidOrderItemError):
        orders_service._cart_item_from_input(
            catalogo, OrderItemInput(product_id=uuid4(), quantity=1)
        )
    with pytest.raises(orders_service.InvalidOrderItemError):
        orders_service._cart_item_from_input(
            catalogo, OrderItemInput(product_id=indisponivel.id, quantity=1)
        )


def test_lancamento_manual_recusa_sabor_inexistente_ou_esgotado() -> None:
    catalogo = _catalogo_para_lancamento_manual()
    produto = catalogo.products[0]
    esgotado = produto.groups[0].complements[1]

    with pytest.raises(orders_service.InvalidOrderItemError):
        orders_service._cart_item_from_input(
            catalogo,
            OrderItemInput(product_id=produto.id, quantity=1, complement_ids=[uuid4()]),
        )
    with pytest.raises(orders_service.InvalidOrderItemError):
        orders_service._cart_item_from_input(
            catalogo,
            OrderItemInput(product_id=produto.id, quantity=1, complement_ids=[esgotado.id]),
        )


@pytest.mark.asyncio
async def test_create_order_manual_entra_direto_em_preparando(monkeypatch) -> None:
    """Pulando `NOVO`/Pix: quem lança manualmente já sabe se cobrou ou não."""
    catalogo = _catalogo_para_lancamento_manual()
    produto = catalogo.products[0]
    sabor = produto.groups[0].complements[0]

    chamada: dict[str, object] = {}

    async def _fake_create_order_from_cart(session, **kwargs):
        chamada.update(kwargs)
        return "resultado"

    monkeypatch.setattr(
        orders_service, "create_order_from_cart", _fake_create_order_from_cart
    )

    resultado = await orders_service.create_order_manual(
        None,  # type: ignore[arg-type]
        catalog=catalogo,
        items=[OrderItemInput(product_id=produto.id, quantity=1, complement_ids=[sabor.id])],
        phone="5511990000001",
        customer_name="Balcão",
        fulfillment_type=FulfillmentType.RETIRADA,
        address=None,
        payment_status=orders_service.PaymentStatus.PAGO,
    )

    assert resultado == "resultado"
    assert chamada["status"] == orders_service.OrderStatus.PREPARANDO
    assert chamada["payment_status"] == orders_service.PaymentStatus.PAGO
    assert chamada["channel"] == OrderChannel.ADMIN
    assert chamada["cart"].items[0].product_name == "Pote 500ml"


# ---------------------------------------------------------------------------
# Costura pagamento -> agente
# ---------------------------------------------------------------------------


class _StubSession:
    """Sessão mínima que só registra o que foi chamado na transação."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_notificacao_de_pagamento_comita(monkeypatch) -> None:
    """Regressão: a camada do agente não comita — quem paga é que comita.

    Sem este commit, o Pix era aprovado mas a conversa ficava presa em
    "aguardando_pagamento" e o cliente nunca recebia a confirmação: as
    alterações do agente morriam ao fechar a sessão.
    """
    from app import api as webhooks

    chamadas: list[object] = []

    async def fake_notify(session, order_id) -> None:
        chamadas.append(order_id)

    monkeypatch.setattr(webhooks, "notify_payment_approved", fake_notify)

    session = _StubSession()
    await webhooks.avisar_agente_do_pagamento(session, uuid4())

    assert len(chamadas) == 1, "o agente precisa ser avisado"
    assert session.commits == 1, "sem commit a conversa fica presa"


@pytest.mark.asyncio
async def test_falha_ao_notificar_nao_derruba_o_pagamento(monkeypatch) -> None:
    """Erro do agente não pode fazer o Mercado Pago reenviar para sempre."""
    from app import api as webhooks

    async def explode(session, order_id) -> None:
        raise RuntimeError("agente fora do ar")

    monkeypatch.setattr(webhooks, "notify_payment_approved", explode)

    session = _StubSession()
    await webhooks.avisar_agente_do_pagamento(session, uuid4())

    assert session.rollbacks == 1, "transação suja precisa ser desfeita"
