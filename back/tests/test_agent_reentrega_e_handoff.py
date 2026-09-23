"""Duas garantias da borda do canal, aprendidas num atendimento real.

1. **Reentrega.** O WhatsApp entrega pelo menos uma vez. Quando a mesma
   mensagem chegou duas vezes, o agente rodou duas vezes: a segunda já com o
   estado adiantado, respondendo "não entendi" a uma pergunta que ninguém
   tinha feito — e três dessas levaram a conversa para atendimento humano em
   quatro mensagens.
2. **Volta do handoff.** Escalar para humano só ajuda se houver humano. Sem
   resposta da loja dentro da janela, o bot reassume em vez de deixar o
   cliente falando sozinho.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.machine import human_on_the_line, run
from app.agent.runner import handle_inbound
from app.agent.whatsapp import InboundMessage
from app.core.config import get_settings
from app.domain.enums import ConversationState as S
from app.domain.enums import Intent

from tests.test_agent_machine import build_deps, build_session, nlu


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
async def test_bot_fica_calado_enquanto_a_loja_responde() -> None:
    deps, session = build_deps(), build_session(S.ATENDIMENTO_HUMANO)
    session.handoff = True
    session.touch_handoff()

    assert human_on_the_line(session) is True
    assert (await run(deps, session, nlu(Intent.SAUDAR), "oi")).replies == []


@pytest.mark.asyncio
async def test_bot_reassume_quando_ninguem_atende(monkeypatch) -> None:
    deps, session = build_deps(), build_session(S.ATENDIMENTO_HUMANO)
    session.handoff = True
    session.touch_handoff()
    monkeypatch.setattr(get_settings(), "handoff_return_minutes", 0)

    result = await run(deps, session, nlu(Intent.SAUDAR), "oi")

    assert result.replies, "o cliente escreveu de novo e ninguém respondeu"
    assert session.handoff is False
    assert session.state is S.ESCOLHENDO_PRODUTO
    assert "handoff_since" not in session.slots


@pytest.mark.asyncio
async def test_conversa_antiga_sem_marca_nao_fica_presa() -> None:
    """Conversas que entraram em handoff antes desta versão não têm marca."""
    session = build_session(S.ATENDIMENTO_HUMANO)
    session.handoff = True
    assert human_on_the_line(session) is False
