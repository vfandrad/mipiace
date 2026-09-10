"""Contrato do cliente de LLM usado pelo agente.

O LLM tem um papel deliberadamente estreito: ele lê a mensagem do cliente e
devolve *dados estruturados* (intenção + campos extraídos). Ele nunca escolhe
o próximo estado, nunca calcula preço e nunca emite id de produto — quem faz
isso é a máquina de estados com o catálogo real em mãos.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from pydantic import BaseModel, Field

from app.domain.catalog import CatalogSnapshot
from app.domain.enums import ConversationState, Intent


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
    """

    intent: Intent = Intent.DESCONHECIDO
    confidence: float = 0.0
    product_query: str | None = None
    complement_queries: list[str] = Field(default_factory=list)
    quantity: int | None = None
    address: ExtractedAddress | None = None
    customer_name: str | None = None
    note: str | None = None

    # Metadados para auditoria/custo (gravados em conversation_messages)
    model: str | None = None
    usage: dict[str, Any] | None = None


class LLMClient(Protocol):
    """Implementado por AnthropicLLMClient e FakeLLMClient."""

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
