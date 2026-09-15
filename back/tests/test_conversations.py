"""Handoff: assumir o atendimento e devolver a conversa para o bot.

O ponto delicado é a volta. A máquina de estados cala o bot pelo ESTADO
(`machine.run` devolve silêncio em ATENDIMENTO_HUMANO), enquanto o painel
mexe no BOOLEANO `handoff`. Se os dois não andarem juntos, uma conversa que o
bot escalou sozinho nunca mais é atendida.
"""

from __future__ import annotations

import pytest

from app.domain.enums import ConversationState as S
from app.services import conversations as conversations_service


class _FakeConversation:
    """Só os campos que o toggle de handoff toca."""

    def __init__(self, state: S, *, handoff: bool = False, fail_count: int = 0) -> None:
        self.state = state.value
        self.handoff = handoff
        self.fail_count = fail_count
        self.cart = [{"product_name": "Pote 500ml"}]


class _FlushOnlySession:
    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


@pytest.mark.asyncio
async def test_assumir_atendimento_apenas_liga_o_booleano() -> None:
    """Assumir não mexe no estado: o cliente pode estar no meio do pedido."""
    conversa = _FakeConversation(S.ESCOLHENDO_PRODUTO)
    session = _FlushOnlySession()

    await conversations_service.set_handoff(session, conversa, handoff=True)

    assert conversa.handoff is True
    assert conversa.state == S.ESCOLHENDO_PRODUTO.value, "o estado não pode mudar"


@pytest.mark.asyncio
async def test_devolver_ao_bot_tira_de_atendimento_humano() -> None:
    """Regressão: sem isto a conversa escalada pelo bot ficava muda para sempre.

    `machine.run` responde silêncio enquanto o estado for ATENDIMENTO_HUMANO,
    e nada no código de produção fazia a transição de volta.
    """
    conversa = _FakeConversation(S.ATENDIMENTO_HUMANO, handoff=True, fail_count=3)
    session = _FlushOnlySession()

    await conversations_service.set_handoff(session, conversa, handoff=False)

    assert conversa.handoff is False
    assert conversa.state == S.SAUDACAO.value, "o bot precisa voltar a responder"


@pytest.mark.asyncio
async def test_devolver_ao_bot_zera_o_contador_de_falhas() -> None:
    """Senão a próxima incompreensão escalaria a conversa na hora de novo."""
    conversa = _FakeConversation(S.ATENDIMENTO_HUMANO, handoff=True, fail_count=3)
    session = _FlushOnlySession()

    await conversations_service.set_handoff(session, conversa, handoff=False)

    assert conversa.fail_count == 0


@pytest.mark.asyncio
async def test_devolver_ao_bot_preserva_o_carrinho() -> None:
    """O cliente pode ter montado o pedido antes de pedir um atendente."""
    conversa = _FakeConversation(S.ATENDIMENTO_HUMANO, handoff=True)
    session = _FlushOnlySession()

    await conversations_service.set_handoff(session, conversa, handoff=False)

    assert conversa.cart == [{"product_name": "Pote 500ml"}]


@pytest.mark.asyncio
async def test_devolver_ao_bot_fora_de_atendimento_humano_nao_mexe_no_estado() -> None:
    """Handoff ligado no meio do pedido: desligar só devolve o fluxo onde estava."""
    conversa = _FakeConversation(S.COLETANDO_ENDERECO, handoff=True, fail_count=2)
    session = _FlushOnlySession()

    await conversations_service.set_handoff(session, conversa, handoff=False)

    assert conversa.state == S.COLETANDO_ENDERECO.value
    assert conversa.fail_count == 2, "não era uma escalada do bot; nada a zerar"


def test_transicao_de_volta_e_permitida_pela_maquina() -> None:
    """O estado para onde o toggle devolve precisa ser alcançável de verdade."""
    from app.agent.states import can_transition

    assert can_transition(S.ATENDIMENTO_HUMANO, S.SAUDACAO)
