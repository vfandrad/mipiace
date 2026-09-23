"""Contrato do cliente de LLM usado pelo agente, e a escolha de qual usar.

O LLM tem um papel deliberadamente estreito: ele lê a mensagem do cliente e
devolve *dados estruturados* (intenção + campos extraídos). Ele nunca escolhe
o próximo estado, nunca calcula preço e nunca emite id de produto — quem faz
isso é a máquina de estados com o catálogo real em mãos.

`FAKE_MODE=true` é a chave da escolha: o sistema inteiro roda sem nenhuma
chave externa. Com `fake_mode=false` usamos a OpenAI; se a chave não estiver
configurada caímos no cliente falso e avisamos no log — melhor um agente
limitado do que um agente que responde erro 500 no WhatsApp.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Protocol, Sequence

from pydantic import BaseModel, Field

from app.domain.catalog import CatalogSnapshot
from app.core.config import get_settings
from app.domain.enums import ConversationState, Intent

logger = logging.getLogger(__name__)


class Turn(BaseModel):
    """Uma fala do histórico recente da conversa."""

    role: str  # "cliente" | "agente"
    content: str


class ExtractedAddress(BaseModel):
    rua: str | None = None
    numero: str | None = None
    bairro: str | None = None
    complemento: str | None = None
    referencia: str | None = None

    @property
    def is_complete(self) -> bool:
        return bool(self.rua and self.numero and self.bairro)


class NluResult(BaseModel):
    """Saída estruturada da interpretação de uma mensagem.

    `product_query` e `complement_queries` são TEXTO LIVRE (ex.: "pote grande",
    "pistache"), não ids. A resolução para ids reais acontece depois, contra o
    CatalogSnapshot — é essa separação que impede o agente de aceitar um sabor
    alucinado.

    `product_name` e `complement_names` são o outro caminho: o palpite do
    modelo sobre QUAL item do cardápio o cliente quis dizer, escrito com o nome
    exato do cardápio. Sem isso, "quero um pote grande" não tinha como virar
    "G - 500ml" — o texto do cliente não parece com o nome do produto, e o
    modelo era proibido de traduzir. Continua não havendo invenção: o `runner`
    descarta qualquer nome que não exista no `CatalogSnapshot`.
    """

    intent: Intent = Intent.DESCONHECIDO
    confidence: float = 0.0
    product_query: str | None = None
    complement_queries: list[str] = Field(default_factory=list)
    product_name: str | None = None
    complement_names: list[str] = Field(default_factory=list)
    quantity: int | None = None
    address: ExtractedAddress | None = None
    customer_name: str | None = None

    # Metadados para auditoria/custo (gravados em conversation_messages)
    model: str | None = None
    usage: dict[str, Any] | None = None


class LLMClient(Protocol):
    """Implementado por OpenAILLMClient e FakeLLMClient."""

    name: str

    async def extract(
        self,
        *,
        state: ConversationState,
        catalog: CatalogSnapshot,
        history: Sequence[Turn],
        message: str,
    ) -> NluResult:
        """Interpreta a mensagem do cliente no contexto do estado atual."""
        ...


@lru_cache
def get_llm_client() -> LLMClient:
    """Cliente de LLM do processo (cacheado: o SDK reaproveita a conexão)."""
    settings = get_settings()

    if not settings.fake_mode and settings.openai_api_key:
        from app.agent.llm_openai import OpenAILLMClient

        return OpenAILLMClient(settings)

    if not settings.fake_mode:
        logger.warning(
            "FAKE_MODE=false mas OPENAI_API_KEY não está configurada; "
            "usando o LLM falso."
        )

    from app.agent.llm_fake import FakeLLMClient

    return FakeLLMClient()
