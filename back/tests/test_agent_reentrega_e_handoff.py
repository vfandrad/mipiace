"""Duas garantias da borda do canal, aprendidas em conversa real.

1. **Reentrega.** O WhatsApp entrega pelo menos uma vez. Quando a mesma
   mensagem chegava duas vezes, o agente rodava duas vezes — a segunda já com
   o estado adiantado, respondendo "não entendi" a uma pergunta que ninguém
   tinha feito.
2. **Volta do handoff.** Escalar para humano só ajuda se houver humano. Sem
   resposta da loja dentro da janela, o bot reassume em vez de deixar o
   cliente falando sozinho.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.machine import run
from app.agent.operations import human_on_the_line
from app.agent.plan import Action, AgentPlan
from app.agent.runner import handle_inbound
from app.agent.whatsapp import InboundMessage
from app.core.config import get_settings
from app.domain.enums import ConversationState as S
from tests.test_agent_machine import build_deps, build_session, op, plano


class _JaVista:
    """Banco que responde "essa mensagem já existe" e nada mais.

    Qualquer outro uso do banco neste teste seria sinal de que o agente passou
    do ponto em que deveria ter parado.
    """

    def __init__(self) -> None:
        self.consultas = 0

    async def execute(self, statement: Any, params: Any = None) -> Any:
        self.consultas += 1
        assert "provider_message_id" in str(statement), (
            "depois de reconhecer a reentrega, o agente não deveria tocar no banco"
        )

        class _Result:
            @staticmethod
            def first() -> tuple[int, ...]:
                return (1,)

        return _Result()


@pytest.mark.asyncio
async def test_mensagem_reentregue_nao_roda_o_agente_de_novo() -> None:
    db = _JaVista()
    replies = await handle_inbound(
        db,
        InboundMessage(phone="5511999990000", text="oi", provider_message_id="ABC123"),
    )
    assert replies == []
    assert db.consultas == 1


@pytest.mark.asyncio
async def test_mensagem_sem_id_do_provedor_segue_o_fluxo() -> None:
    """Simulador e CLI não têm id; não podem ser confundidos com reentrega."""
    from app.agent.session import already_seen

    assert await already_seen(_JaVista(), None) is False


@pytest.mark.asyncio
async def test_bot_nao_conduz_o_pedido_enquanto_a_loja_atende() -> None:
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.REQUEST_HUMAN)), "quero um atendente")

    assert human_on_the_line(session) is True
    replies = await run(deps, session, AgentPlan(), "oi?")
    # Não conduz, mas também não some: avisa que está esperando.
    assert replies and "aguardando" in replies[0].lower()


@pytest.mark.asyncio
async def test_bot_reassume_quando_ninguem_atende(monkeypatch) -> None:
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.REQUEST_HUMAN)), "atendente")
    monkeypatch.setattr(get_settings(), "handoff_return_minutes", 0)

    replies = await run(
        deps, session, plano(op(Action.ADD_ITEM, product_name="Casquinha")), "quero casquinha"
    )

    assert replies
    assert session.handoff is False
    assert session.state is S.CONVERSANDO
    assert "handoff_since" not in session.slots


@pytest.mark.asyncio
async def test_conversa_antiga_sem_marca_nao_fica_presa() -> None:
    """Conversas que entraram em handoff antes desta versão não têm marca."""
    session = build_session(S.ATENDIMENTO_HUMANO)
    session.handoff = True
    assert human_on_the_line(session) is False


@pytest.mark.asyncio
async def test_atendimento_humano_nunca_emudece() -> None:
    """A garantia mais cara do agente: em handoff ele para de conduzir, não de falar.

    O slot `handoff_avisado` era gravado uma vez e nunca limpo, então a partir
    da TERCEIRA mensagem o turno devolvia lista vazia para sempre. Três
    clientes simulados bateram nisso — "alooo? tem alguém aí?" caía no vazio.
    """
    from tests.test_agent_machine import build_deps, build_session, op, plano  # noqa: PLC0415

    deps, session = build_deps(), build_session()

    escalou = await run(deps, session, plano(op(Action.REQUEST_HUMAN)), "quero falar com alguem")
    assert escalou, "escalar já tem de responder"
    assert session.handoff

    # As mensagens seguintes, todas sem operação de pedido: nenhuma pode calar.
    for numero, fala in enumerate(["alooo?", "tem alguem ai?", "oi???", "voces sumiram?"], 2):
        respostas = await run(deps, session, plano(op(Action.REQUEST_HUMAN)), fala)
        assert respostas, f"o bot ficou mudo na mensagem {numero}: {fala!r}"
        assert any(r.strip() for r in respostas), f"resposta vazia em {fala!r}"
