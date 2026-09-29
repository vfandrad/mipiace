"""Retentativa com backoff nas chamadas à OpenAI (chat e transcrição).

O laço de backoff em si já vem pronto no SDK da OpenAI — não é reescrito aqui.
O que este teste garante é que `LLM_MAX_RETRIES` chega de fato até o cliente
que o SDK usa por baixo, para as duas chamadas (interpretar mensagem e
transcrever áudio).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agente import OpenAIAudioTranscriber, OpenAILLMClient
from app.configuracao import get_settings


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
