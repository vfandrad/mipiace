"""Caminho do pagamento: o código de maior risco do backend.

As três garantias que o webhook do Mercado Pago precisa dar, e que estes
testes protegem:

1. **Idempotência** — o MP reenvia a mesma notificação; o cliente não pode ser
   avisado duas vezes nem o pedido pago duas vezes.
2. **Nunca confiar no payload** — o corpo do webhook só diz *qual* pagamento
   mudou; o status vem de uma consulta à API do provedor.
3. **Nunca derrubar por causa do agente** — se avisar o cliente falhar, o
   pagamento continua registrado.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.api.routes import webhooks
from app.domain.enums import OrderStatus, PaymentStatus
from app.services import payments as payments_service
from app.services.pix_provider import (
    FakePaymentProvider,
    PaymentStatusResult,
    map_status,
)

# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------

class _FakeOrder:
    def __init__(
        self,
        *,
        status: OrderStatus = OrderStatus.NOVO,
        payment_status: PaymentStatus = PaymentStatus.PENDENTE,
    ) -> None:
        self.id = uuid4()
        self.code = "MP-0042"
        self.status = status
        self.payment_status = payment_status
        self.paid_at: datetime | None = None


class _FakePayment:
    def __init__(self, order_id) -> None:
        self.order_id = order_id
        self.status = PaymentStatus.PENDENTE
        self.raw_payload: dict | None = None
        self.provider_payment_id = "mp-1"


class _Session:
    """Sessão mínima: só conta flush/commit/rollback."""

    def __init__(self) -> None:
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _wire(monkeypatch, *, payment=None, order=None) -> None:
    """Liga as buscas de banco de `apply_payment_result` a objetos em memória."""

    async def _get_payment_by_provider_id(session, *, provider, provider_payment_id):
        return payment

    async def _get_order(session, order_id):
        return order

    monkeypatch.setattr(
        payments_service, "get_payment_by_provider_id", _get_payment_by_provider_id
    )
    monkeypatch.setattr(payments_service, "get_order", _get_order)


def _result(status: PaymentStatus, *, external_reference: str | None = None):
    return PaymentStatusResult(
        provider_payment_id="mp-1",
        status=status,
        external_reference=external_reference,
        amount=Decimal("37.00"),
    )


# ---------------------------------------------------------------------------
# apply_payment_result — o que o webhook realmente faz com o pedido
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pix_pago_move_o_pedido_para_preparando(monkeypatch) -> None:
    """Quem põe o pedido na fila da produção é o pagamento, não o lojista."""
    order = _FakeOrder()
    _wire(monkeypatch, payment=_FakePayment(order.id), order=order)

    resultado, aprovado_agora = await payments_service.apply_payment_result(
        _Session(), _result(PaymentStatus.PAGO), provider_name="fake"
    )

    assert aprovado_agora is True
    assert resultado.payment_status is PaymentStatus.PAGO
    assert resultado.status is OrderStatus.PREPARANDO
    assert resultado.paid_at is not None


@pytest.mark.asyncio
async def test_pagamento_repetido_nao_avisa_o_cliente_de_novo(monkeypatch) -> None:
    """Idempotência: o MP reenvia a notificação do mesmo pagamento aprovado."""
    order = _FakeOrder(status=OrderStatus.PREPARANDO, payment_status=PaymentStatus.PAGO)
    _wire(monkeypatch, payment=_FakePayment(order.id), order=order)

    _, aprovado_agora = await payments_service.apply_payment_result(
        _Session(), _result(PaymentStatus.PAGO), provider_name="fake"
    )

    assert aprovado_agora is False, "avisar de novo duplicaria a mensagem ao cliente"


@pytest.mark.asyncio
async def test_pedido_ja_em_entrega_nao_volta_para_preparando(monkeypatch) -> None:
    """Notificação atrasada não pode puxar o pedido para trás no Kanban."""
    order = _FakeOrder(status=OrderStatus.ENTREGA, payment_status=PaymentStatus.PAGO)
    _wire(monkeypatch, payment=_FakePayment(order.id), order=order)

    resultado, _ = await payments_service.apply_payment_result(
        _Session(), _result(PaymentStatus.PAGO), provider_name="fake"
    )

    assert resultado.status is OrderStatus.ENTREGA


@pytest.mark.asyncio
async def test_pix_expirado_marca_o_pagamento_sem_cancelar_o_pedido(monkeypatch) -> None:
    order = _FakeOrder()
    _wire(monkeypatch, payment=_FakePayment(order.id), order=order)

    resultado, aprovado_agora = await payments_service.apply_payment_result(
        _Session(), _result(PaymentStatus.EXPIRADO), provider_name="fake"
    )

    assert aprovado_agora is False
    assert resultado.payment_status is PaymentStatus.EXPIRADO
    assert resultado.status is OrderStatus.NOVO, "o lojista é quem cancela o pedido"


@pytest.mark.asyncio
async def test_expiracao_nao_desfaz_um_pagamento_ja_confirmado(monkeypatch) -> None:
    """Evento fora de ordem não pode transformar pedido pago em expirado."""
    order = _FakeOrder(status=OrderStatus.PREPARANDO, payment_status=PaymentStatus.PAGO)
    _wire(monkeypatch, payment=_FakePayment(order.id), order=order)

    resultado, _ = await payments_service.apply_payment_result(
        _Session(), _result(PaymentStatus.EXPIRADO), provider_name="fake"
    )

    assert resultado.payment_status is PaymentStatus.PAGO


@pytest.mark.asyncio
async def test_pagamento_sem_pedido_nao_explode(monkeypatch) -> None:
    """Cobrança de outro sistema chegando no nosso webhook."""
    _wire(monkeypatch, payment=None, order=None)

    resultado, aprovado_agora = await payments_service.apply_payment_result(
        _Session(), _result(PaymentStatus.PAGO), provider_name="fake"
    )

    assert resultado is None and aprovado_agora is False


@pytest.mark.asyncio
async def test_acha_o_pedido_pela_external_reference(monkeypatch) -> None:
    """Sem linha em `payments`, o id do pedido no MP ainda encontra a venda."""
    order = _FakeOrder()
    _wire(monkeypatch, payment=None, order=order)

    resultado, aprovado_agora = await payments_service.apply_payment_result(
        _Session(),
        _result(PaymentStatus.PAGO, external_reference=str(order.id)),
        provider_name="fake",
    )

    assert resultado is order and aprovado_agora is True


@pytest.mark.asyncio
async def test_apply_payment_result_nao_comita(monkeypatch) -> None:
    """Regra do projeto: quem fecha a transação é a rota, não o service."""
    order = _FakeOrder()
    _wire(monkeypatch, payment=_FakePayment(order.id), order=order)
    session = _Session()

    await payments_service.apply_payment_result(
        session, _result(PaymentStatus.PAGO), provider_name="fake"
    )

    assert session.commits == 0
    assert session.flushes == 1


# ---------------------------------------------------------------------------
# Tradução do vocabulário do Mercado Pago
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("mp_status", "esperado"),
    [
        ("approved", PaymentStatus.PAGO),
        ("authorized", PaymentStatus.PAGO),
        ("pending", PaymentStatus.PENDENTE),
        ("in_process", PaymentStatus.PENDENTE),
        ("rejected", PaymentStatus.CANCELADO),
        ("cancelled", PaymentStatus.CANCELADO),
        ("refunded", PaymentStatus.REEMBOLSADO),
        ("charged_back", PaymentStatus.REEMBOLSADO),
        ("status_desconhecido", PaymentStatus.PENDENTE),
    ],
)
def test_traducao_de_status_do_mercado_pago(mp_status, esperado) -> None:
    assert map_status(mp_status) is esperado


def test_pix_expirado_vem_no_status_detail() -> None:
    """O MP não tem status "expirado": ele vem no detalhe."""
    assert map_status("cancelled", "expired") is PaymentStatus.EXPIRADO


# ---------------------------------------------------------------------------
# Leitura do payload do webhook (o MP manda o id em vários formatos)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("body", "query", "esperado"),
    [
        ({"data": {"id": "123"}}, {}, "123"),
        ({}, {"data.id": "456"}, "456"),
        ({}, {"id": "789"}, "789"),
        ({"resource": "https://api.mercadopago.com/v1/payments/999"}, {}, "999"),
        ({}, {}, None),
    ],
)
def test_extrai_o_id_do_pagamento(body, query, esperado) -> None:
    assert webhooks._extract_payment_id(body, query) == esperado


def test_evento_repetido_tem_o_mesmo_id() -> None:
    """A chave de idempotência precisa ser estável entre reenvios."""
    body = {"id": 55, "action": "payment.updated"}
    assert webhooks._event_id(body, "123") == webhooks._event_id(body, "123")


def test_id_do_evento_sem_id_proprio_usa_acao_e_pagamento() -> None:
    assert webhooks._event_id({"action": "payment.updated"}, "123") == (
        "payment.updated:123"
    )


# ---------------------------------------------------------------------------
# Assinatura do webhook
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def _assinar(secret: str, payment_id: str, request_id: str, ts: str) -> str:
    manifest = f"id:{payment_id};request-id:{request_id};ts:{ts};"
    return hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()


def test_assinatura_valida_e_aceita(monkeypatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mp_webhook_secret", "segredo", raising=False)

    v1 = _assinar("segredo", "123", "req-1", "1700000000")
    request = _FakeRequest(
        {"x-signature": f"ts=1700000000,v1={v1}", "x-request-id": "req-1"}
    )

    assert webhooks._valid_signature(request, "123") is True


def test_assinatura_forjada_e_recusada(monkeypatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mp_webhook_secret", "segredo", raising=False)

    request = _FakeRequest(
        {"x-signature": "ts=1700000000,v1=deadbeef", "x-request-id": "req-1"}
    )

    assert webhooks._valid_signature(request, "123") is False


def test_sem_segredo_configurado_a_validacao_e_pulada(monkeypatch) -> None:
    """MP_WEBHOOK_SECRET é opcional na conta do MP; travar deixaria o MVP sem webhook."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mp_webhook_secret", None, raising=False)

    assert webhooks._valid_signature(_FakeRequest({}), "123") is True


# ---------------------------------------------------------------------------
# Provedor falso — é ele que sustenta o FAKE_MODE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pix_falso_e_deterministico() -> None:
    """Mesmo pedido e mesmo valor geram o mesmo copia-e-cola."""
    provider = FakePaymentProvider()
    order_id = uuid4()

    async def cobrar():
        return await provider.create_pix_charge(
            order_id=order_id, order_code="MP-0042", amount=Decimal("37.00")
        )

    assert (await cobrar()).qr_code == (await cobrar()).qr_code


@pytest.mark.asyncio
async def test_pix_falso_so_fica_pago_depois_de_aprovado() -> None:
    provider = FakePaymentProvider()
    charge = await provider.create_pix_charge(
        order_id=uuid4(), order_code="MP-0043", amount=Decimal("21.00")
    )

    antes = await provider.get_payment(charge.provider_payment_id)
    assert antes.status is PaymentStatus.PENDENTE

    provider.approve(charge.provider_payment_id)

    depois = await provider.get_payment(charge.provider_payment_id)
    assert depois.status is PaymentStatus.PAGO


@pytest.mark.asyncio
async def test_pix_falso_carrega_o_pedido_no_id_da_cobranca() -> None:
    """É o que faz `get_payment` continuar funcionando depois de reiniciar."""
    provider = FakePaymentProvider()
    order_id = uuid4()
    charge = await provider.create_pix_charge(
        order_id=order_id, order_code="MP-0044", amount=Decimal("15.50")
    )

    resultado = await provider.get_payment(charge.provider_payment_id)

    assert resultado.external_reference == str(order_id)
