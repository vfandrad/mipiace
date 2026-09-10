"""Fluxo feliz completo: de "oi" até o Pix, e do Pix até a confirmação.

Este é o teste que prova que o agente funciona de ponta a ponta sem n8n, sem
WhatsApp, sem chave de API e sem Postgres: `FakeLLMClient` interpreta,
`ConsoleAdapter` entrega, e a camada de banco é substituída por um repositório
em memória com a mesma superfície de `app.agent.session`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agent import runner
from app.agent.channels.base import InboundMessage
from app.agent.channels.console import ConsoleAdapter
from app.agent.llm.base import Turn
from app.agent.llm.fake import FakeLLMClient
from app.agent.machine import AgentDeps
from app.agent.session import ConversationSession
from app.core.config import get_settings
from app.domain.catalog import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
)
from app.domain.enums import ConversationState as S
from app.domain.enums import MessageDirection

PHONE = "5511988887777"


# ---------------------------------------------------------------------------
# Catálogo de gelateria (espelha o que o seed cria)
# ---------------------------------------------------------------------------

def build_catalog() -> CatalogSnapshot:
    pote_id, sabores_id, cobertura_id = uuid4(), uuid4(), uuid4()
    pote = CatalogProduct(
        id=pote_id,
        name="Pote 500ml",
        description="Escolha 3 sabores",
        base_price=Decimal("32.00"),
        groups=[
            CatalogGroup(
                id=sabores_id,
                product_id=pote_id,
                name="Sabores",
                min_choices=3,
                max_choices=3,
                is_required=True,
                complements=[
                    CatalogComplement(id=uuid4(), group_id=sabores_id, name=name)
                    for name in (
                        "Pistache",
                        "Morango",
                        "Chocolate Belga",
                        "Limão Siciliano",
                        "Doce de Leite",
                    )
                ],
            ),
            CatalogGroup(
                id=cobertura_id,
                product_id=pote_id,
                name="Cobertura",
                min_choices=0,
                max_choices=1,
                is_required=False,
                complements=[
                    CatalogComplement(
                        id=uuid4(),
                        group_id=cobertura_id,
                        name="Calda de Chocolate",
                        extra_price=Decimal("3.00"),
                    )
                ],
            ),
        ],
    )
    casquinha = CatalogProduct(id=uuid4(), name="Casquinha", base_price=Decimal("9.00"))
    pote240 = CatalogProduct(id=uuid4(), name="Pote 240ml", base_price=Decimal("18.00"))
    return CatalogSnapshot(products=[pote, pote240, casquinha])


# ---------------------------------------------------------------------------
# Banco em memória com a mesma superfície de app.agent.session
# ---------------------------------------------------------------------------

class FakeStore:
    """Guarda conversas e mensagens em dicionários, sem Postgres."""

    def __init__(self) -> None:
        self.conversations: dict[tuple[str, str], ConversationSession] = {}
        self.messages: list[dict[str, Any]] = []

    async def load_or_create(self, db, phone: str, channel: str = "whatsapp"):
        key = (phone, channel)
        if key not in self.conversations:
            self.conversations[key] = ConversationSession(
                id=uuid4(), phone=phone, channel=channel, state=S.SAUDACAO
            )
        return self.conversations[key]

    async def save_session(self, db, session: ConversationSession) -> None:
        self.conversations[(session.phone, session.channel)] = session

    async def log_message(self, db, **kwargs) -> None:
        self.messages.append(kwargs)

    async def recent_turns(self, db, conversation_id: UUID, limit: int = 8):
        turns = [
            Turn(
                role="cliente"
                if m["direction"] is MessageDirection.ENTRADA
                else "agente",
                content=m["content"],
            )
            for m in self.messages
            if m["conversation_id"] == conversation_id
        ]
        return turns[-limit:]

    async def find_by_active_order(self, db, order_id: UUID):
        return next(
            (
                c
                for c in self.conversations.values()
                if c.active_order_id == order_id
            ),
            None,
        )


class FakeOrder:
    def __init__(self, total: Decimal) -> None:
        self.id = uuid4()
        self.code = "MP-1042"
        self.subtotal = total
        self.delivery_fee = Decimal("5.00")
        self.total = total + self.delivery_fee


class FakePix:
    def __init__(self) -> None:
        self.provider = "fake"
        self.provider_payment_id = "fake-pix-1"
        self.qr_code = "00020126580014BR.GOV.BCB.PIX-COPIA-E-COLA-MIPIACE"


class FakeSummary:
    code = "MP-1042"
    status = "novo"
    payment_status = "pago"
    total = Decimal("37.00")


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch):
    """Monta o agente inteiro com fakes e devolve um ajudante de conversa."""
    store = FakeStore()
    adapter = ConsoleAdapter()
    catalog = build_catalog()
    created: dict[str, Any] = {}

    async def _create_order(db, **kwargs):
        created["kwargs"] = kwargs
        order = FakeOrder(kwargs["cart"].subtotal)
        created["order"] = order
        return order

    async def _create_pix(db, order_id):
        created["pix_for"] = order_id
        return FakePix()

    async def _order_summary(db, order_id):
        return FakeSummary()

    async def _fetch_catalog(db):
        return catalog

    async def _build_deps(db, snapshot, session):
        return AgentDeps(
            db=db,
            catalog=snapshot,
            settings=get_settings(),
            create_order=_create_order,
            create_pix=_create_pix,
            order_summary=_order_summary,
            saved_address=None,
        )

    monkeypatch.setattr(runner, "load_or_create", store.load_or_create)
    monkeypatch.setattr(runner, "save_session", store.save_session)
    monkeypatch.setattr(runner, "log_message", store.log_message)
    monkeypatch.setattr(runner, "recent_turns", store.recent_turns)
    monkeypatch.setattr(runner, "find_by_active_order", store.find_by_active_order)
    monkeypatch.setattr(runner, "_fetch_catalog", _fetch_catalog)
    monkeypatch.setattr(runner, "_build_deps", _build_deps)
    monkeypatch.setattr(runner, "get_llm_client", lambda: FakeLLMClient())
    monkeypatch.setattr(runner, "get_channel_adapter", lambda name="whatsapp": adapter)

    class Flow:
        store = None

        async def say(self, text: str) -> list[str]:
            return await runner.handle_inbound(
                object(),  # a "sessão de banco" nunca é usada pelos fakes
                InboundMessage(phone=PHONE, text=text),
                channel_name="simulador",
            )

        @property
        def state(self) -> S:
            return store.conversations[(PHONE, "simulador")].state

        @property
        def conversation(self) -> ConversationSession:
            return store.conversations[(PHONE, "simulador")]

    helper = Flow()
    helper.store = store
    helper.adapter = adapter
    helper.created = created
    return helper


# ---------------------------------------------------------------------------
# O fluxo feliz, passo a passo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fluxo_feliz_ate_o_pix(flow) -> None:
    # 1. Saudação: apresenta o cardápio e abre a escolha de produto.
    replies = await flow.say("oi")
    assert flow.state is S.ESCOLHENDO_PRODUTO
    assert any("Pote 500ml" in reply for reply in replies)

    # 2. Produto com grupo obrigatório: entra na personalização.
    replies = await flow.say("quero um pote 500ml")
    assert flow.state is S.PERSONALIZANDO_ITEM
    assert "Sabores" in replies[0]
    assert flow.conversation.cart.is_empty

    # 3. Os três sabores de uma vez fecham o grupo obrigatório.
    replies = await flow.say("pistache, morango e chocolate belga")
    assert flow.state is S.REVISANDO_CARRINHO
    cart = flow.conversation.cart
    assert len(cart.items) == 1
    assert [c.name for c in cart.items[0].complements] == [
        "Pistache",
        "Morango",
        "Chocolate Belga",
    ]
    assert cart.subtotal == Decimal("32.00")

    # 4. Fechar o pedido vai direto para a coleta de endereço — a loja só
    #    trabalha com entrega, não pergunta mais a modalidade.
    replies = await flow.say("pode fechar")
    assert flow.state is S.COLETANDO_ENDERECO
    assert "endereço" in replies[0].lower()

    # 5. Endereço completo leva ao resumo final com taxa e total.
    replies = await flow.say("Rua das Flores, 123, bairro Centro")
    assert flow.state is S.CONFIRMANDO_PEDIDO
    resumo = replies[0]
    assert "R$ 32,00" in resumo          # subtotal
    assert "R$ 5,00" in resumo           # taxa de entrega
    assert "R$ 37,00" in resumo          # total
    assert "Rua Das Flores" in resumo

    # 6. Confirmação cria o pedido, gera o Pix e trava em AGUARDANDO_PAGAMENTO.
    replies = await flow.say("sim")
    assert flow.state is S.AGUARDANDO_PAGAMENTO
    assert "PIX-COPIA-E-COLA-MIPIACE" in replies[0]
    assert "MP-1042" in replies[0]
    assert flow.conversation.cart.is_empty
    order = flow.created["order"]
    assert flow.conversation.active_order_id == order.id
    assert flow.created["pix_for"] == order.id

    # O endereço chegou ao serviço de pedidos no formato do contrato.
    address = flow.created["kwargs"]["address"]
    assert address["rua"] == "Rua Das Flores"
    assert address["numero"] == "123"
    assert address["bairro"] == "Centro"

    # 7. O webhook de pagamento fecha a conversa.
    await runner.notify_payment_approved(object(), order.id)
    assert flow.state is S.CONCLUIDO
    assert any("Pagamento confirmado" in text for _, text in flow.adapter.sent)


@pytest.mark.asyncio
async def test_todas_as_respostas_passaram_pelo_canal(flow) -> None:
    replies = await flow.say("oi")
    assert flow.adapter.replies_for(PHONE) == replies


@pytest.mark.asyncio
async def test_conversa_e_registrada_para_auditoria(flow) -> None:
    await flow.say("oi")
    entradas = [m for m in flow.store.messages if m["direction"] is MessageDirection.ENTRADA]
    saidas = [m for m in flow.store.messages if m["direction"] is MessageDirection.SAIDA]
    assert len(entradas) == 1
    assert entradas[0]["detected_intent"] == "saudar"
    assert entradas[0]["llm_model"] == "fake-rules-v1"
    assert entradas[0]["llm_usage"] is not None
    assert saidas


@pytest.mark.asyncio
async def test_pedir_atendente_silencia_o_bot(flow) -> None:
    await flow.say("oi")
    replies = await flow.say("quero falar com um atendente")
    assert replies
    assert flow.state is S.ATENDIMENTO_HUMANO
    assert flow.conversation.handoff is True

    # A partir daqui o bot não responde mais nada.
    assert await flow.say("e aí, tem novidade?") == []


@pytest.mark.asyncio
async def test_item_fora_do_cardapio_nao_entra_no_carrinho(flow) -> None:
    await flow.say("oi")
    replies = await flow.say("quero uma pizza de calabresa")
    assert flow.conversation.cart.is_empty
    assert flow.state is S.ESCOLHENDO_PRODUTO
    assert replies


@pytest.mark.asyncio
async def test_cancelar_no_meio_do_pedido(flow) -> None:
    await flow.say("oi")
    await flow.say("casquinha")
    assert not flow.conversation.cart.is_empty

    replies = await flow.say("quero cancelar")
    assert flow.state is S.CANCELADO
    assert flow.conversation.cart.is_empty
    assert "cancelei" in replies[0].lower()

    # E uma nova mensagem recomeça a conversa.
    await flow.say("oi de novo")
    assert flow.state is S.ESCOLHENDO_PRODUTO
