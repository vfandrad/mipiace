"""Escolha do cliente de LLM.

`FAKE_MODE=true` é a chave: o sistema inteiro roda sem nenhuma chave externa.
Com `fake_mode=false`, `LLM_PROVIDER` escolhe entre "anthropic" e "openai". Se
a chave do provider escolhido não estiver configurada, caímos no cliente falso
e avisamos no log — melhor um agente limitado do que um agente que responde
erro 500 para o cliente no WhatsApp.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.agent.llm.base import LLMClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_llm_client() -> LLMClient:
    """Cliente de LLM do processo (cacheado: o SDK reaproveita a conexão)."""
    settings = get_settings()

    if settings.fake_mode:
        from app.agent.llm.fake import FakeLLMClient

        return FakeLLMClient()

    provider = (settings.llm_provider or "anthropic").strip().lower()

    if provider == "openai":
        if not settings.openai_api_key:
            logger.warning(
                "FAKE_MODE=false e LLM_PROVIDER=openai, mas OPENAI_API_KEY não "
                "está configurada; usando o LLM falso."
            )
            from app.agent.llm.fake import FakeLLMClient

            return FakeLLMClient()

        from app.agent.llm.openai_client import OpenAILLMClient

        return OpenAILLMClient(settings)

    if not settings.anthropic_api_key:
        logger.warning(
            "FAKE_MODE=false mas ANTHROPIC_API_KEY não está configurada; "
            "usando o LLM falso."
        )
        from app.agent.llm.fake import FakeLLMClient

        return FakeLLMClient()

    from app.agent.llm.anthropic_client import AnthropicLLMClient

    return AnthropicLLMClient(settings)


def reset_llm_client_cache() -> None:
    """Usado em teste, quando as settings mudam entre casos."""
    get_llm_client.cache_clear()
