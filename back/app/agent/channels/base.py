"""Contrato do canal de mensagens.

A máquina de estados não sabe se está falando com o WhatsApp, com o simulador
de terminal ou com um teste automatizado. Ela só entrega texto para um
ChannelAdapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class InboundMessage(BaseModel):
    """Mensagem recebida, já normalizada e independente de canal."""

    phone: str                       # E.164 sem "+": 5511999998888
    text: str
    provider_message_id: str | None = None
    profile_name: str | None = None
    timestamp: datetime | None = None
    #: True quando a própria conta conectada enviou (lojista respondendo pelo
    #: celular, ou eco do que o bot mandou). Não passa pela IA/máquina de
    #: estados — só é registrada no histórico para o painel espelhar o chat.
    from_me: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class ChannelAdapter(Protocol):
    """Implementado por WhatsAppCloudAdapter e ConsoleAdapter."""

    name: str

    async def send_text(self, to: str, text: str) -> str | None:
        """Envia texto e devolve o id da mensagem no provedor, se houver."""
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Extrai as mensagens de um payload de webhook do provedor."""
        ...
