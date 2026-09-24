"""Contrato do cliente de LLM, e a escolha de qual usar.

O papel da IA é grande no que ela entende e estreito no que ela pode fazer:
ela lê a mensagem do cliente (com a situação do pedido em mãos) e devolve um
`AgentPlan` — as operações que o cliente quis realizar. Ela nunca escolhe o
próximo estado, nunca calcula preço, nunca emite id e nunca cobra. Quem faz
isso é o executor, com o catálogo real em mãos.

`FAKE_MODE=true` é a chave da escolha: o sistema inteiro roda sem nenhuma
chave externa. Com `fake_mode=false` usamos a OpenAI; se a chave não estiver
configurada caímos no cliente falso e avisamos no log — melhor um agente
limitado do que um agente que responde erro 500 no WhatsApp.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from pydantic import BaseModel

from app.agent.plan import AgentPlan
from app.core.config import get_settings
from app.domain.catalog import CatalogSnapshot

logger = logging.getLogger(__name__)


class Turn(BaseModel):
    """Uma fala do histórico recente da conversa."""

    role: str  # "cliente" | "agente"
    content: str


class LLMClient(Protocol):
    """Implementado por OpenAILLMClient e FakeLLMClient."""

    name: str

    async def interpret(
        self,
        *,
        catalog: CatalogSnapshot,
        history: Sequence[Turn],
        message: str,
        situation: str = "",
    ) -> AgentPlan:
        """Traduz a mensagem do cliente em operações sobre o pedido.

        `situation` é o retrato do pedido agora (o que está no carrinho, que
        sabores faltam, se há um resumo aguardando confirmação). É o que
        permite resolver "esse mesmo", "o segundo" e "1 e 3" sem obrigar o
        cliente a repetir nomes.
        """
        ...


@lru_cache
def get_llm_client() -> LLMClient:
    """Cliente de LLM do processo (cacheado: o SDK reaproveita a conexão)."""
    settings = get_settings()

    if not settings.fake_mode and settings.openai_api_key:
        from app.agent.llm_openai import OpenAILLMClient  # noqa: PLC0415

        return OpenAILLMClient(settings)

    if not settings.fake_mode:
        logger.warning(
            "FAKE_MODE=false mas OPENAI_API_KEY não está configurada; "
            "usando o LLM falso."
        )

    from app.agent.llm_fake import FakeLLMClient  # noqa: PLC0415

    return FakeLLMClient()
