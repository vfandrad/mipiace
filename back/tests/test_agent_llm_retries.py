"""Retentativa com backoff nas chamadas à OpenAI (chat e transcrição).

O laço de backoff em si já vem pronto no SDK da OpenAI — não é reescrito aqui.
O que este teste garante é que `LLM_MAX_RETRIES` chega de fato até o cliente
que o SDK usa por baixo, para as duas chamadas (interpretar mensagem e
transcrever áudio).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app import agente as runner
from app.agente import (
    Action,
    AgentDeps,
    AgentPlan,
    ConversationSession,
    OpenAIAudioTranscriber,
    OpenAILLMClient,
    Operation,
    _fallback,
    _interpret,
)
from app.configuracao import get_settings
from app.dominio import CatalogSnapshot
from app.dominio import ConversationState as S


class _AsyncOpenAIFalso:
    """Só registra com que argumentos o SDK real teria sido construído."""

    ultima_chamada: dict[str, Any] | None = None

    def __init__(self, **kwargs: Any) -> None:
        type(self).ultima_chamada = kwargs


@pytest.fixture
def com_chave_e_retries(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(settings, "llm_max_retries", 5)
    monkeypatch.setattr("openai.AsyncOpenAI", _AsyncOpenAIFalso)
    return settings


def test_llm_client_liga_o_max_retries_do_sdk(com_chave_e_retries) -> None:
    OpenAILLMClient(com_chave_e_retries)._ensure_client()
    assert _AsyncOpenAIFalso.ultima_chamada["max_retries"] == 5


def test_audio_transcriber_liga_o_max_retries_do_sdk(com_chave_e_retries) -> None:
    OpenAIAudioTranscriber(com_chave_e_retries)._ensure_client()
    assert _AsyncOpenAIFalso.ultima_chamada["max_retries"] == 5


# ---------------------------------------------------------------------------
# Sanidade do que a tool call devolve — a LLM não é obrigada a ser razoável
# ---------------------------------------------------------------------------

def test_quantidade_absurda_da_llm_e_limitada() -> None:
    """"quero 900000 potes" não pode virar item de carrinho com esse número.

    Não é regra de negócio (a loja não tem um máximo de potes por pedido) —
    é só a trava contra um Pix nonsense se a LLM devolver um número absurdo.
    """
    operacao = OpenAILLMClient._operation(
        {"action": "add_item", "product_name": "Pote 500ml", "quantity": 900000}
    )
    assert operacao.quantity == 50


# ---------------------------------------------------------------------------
# Diferenciar "sistema fora do ar" de "não entendi"
# ---------------------------------------------------------------------------

def _sessao() -> ConversationSession:
    return ConversationSession(id=uuid4(), phone="5511999990000", channel="simulador", state=S.CONVERSANDO)


def _deps() -> AgentDeps:
    return AgentDeps(
        db=None,
        catalog=CatalogSnapshot(),
        settings=get_settings(),
        create_order=None,
        create_pix=None,
        order_summary=None,
    )


@pytest.mark.asyncio
async def test_falha_de_infraestrutura_marca_llm_unavailable(monkeypatch) -> None:
    class _ClienteQueExplode:
        async def interpret(self, **kwargs):
            raise TimeoutError("OpenAI fora do ar")

    monkeypatch.setattr(runner, "get_llm_client", lambda: _ClienteQueExplode())
    plano = await _interpret(None, _sessao(), CatalogSnapshot(), "oi", "")
    assert plano.llm_unavailable is True


def test_fallback_usa_texto_de_instabilidade_quando_e_falha_nossa() -> None:
    """Sistema fora do ar não é a mesma mensagem de 'não entendi' do cliente."""
    deps, session = _deps(), _sessao()
    plano = AgentPlan(llm_unavailable=True)

    replies = _fallback(deps, session, plano)

    assert replies[0] == runner.r.instabilidade(session.id)
    assert replies[0] != runner.r.nao_entendi(session.id)


def test_fallback_usa_nao_entendi_quando_o_cliente_e_que_nao_se_fez_entender() -> None:
    deps, session = _deps(), _sessao()
    plano = AgentPlan()

    replies = _fallback(deps, session, plano)

    assert replies[0] == runner.r.nao_entendi(session.id)


# ---------------------------------------------------------------------------
# Uma tentativa extra de reparo antes da escada de fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plano_malformado_ganha_uma_segunda_chamada(monkeypatch) -> None:
    """Primeira resposta sem nada aproveitável; a segunda vem boa — usa a segunda."""
    chamadas: list[str] = []

    class _ClienteComUmaFalhaDeFormato:
        async def interpret(self, *, situation: str = "", **kwargs):
            chamadas.append(situation)
            if len(chamadas) == 1:
                return AgentPlan(malformed=True)
            return AgentPlan(operations=[Operation(action=Action.SHOW_MENU)])

    monkeypatch.setattr(runner, "get_llm_client", lambda: _ClienteComUmaFalhaDeFormato())

    plano = await _interpret(None, _sessao(), CatalogSnapshot(), "oi", "situação original")

    assert len(chamadas) == 2
    assert plano.malformed is False
    assert plano.operations[0].action.value == "show_menu"
    # O reparo é um empurrão extra na mesma situação, não uma troca de assunto.
    assert "situação original" in chamadas[1]


@pytest.mark.asyncio
async def test_plano_malformado_duas_vezes_segue_para_a_escada_sem_terceira_chamada(
    monkeypatch,
) -> None:
    chamadas = 0

    class _ClienteSempreMalformado:
        async def interpret(self, **kwargs):
            nonlocal chamadas
            chamadas += 1
            return AgentPlan(malformed=True)

    monkeypatch.setattr(runner, "get_llm_client", lambda: _ClienteSempreMalformado())

    plano = await _interpret(None, _sessao(), CatalogSnapshot(), "oi", "")

    assert chamadas == 2
    assert plano.malformed is True
