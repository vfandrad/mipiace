"""Canal em memória.

Serve a três donos: o simulador HTTP, a CLI de terminal e os testes. Como não
sai da máquina, é ele que torna possível exercitar a conversa inteira — de
"oi" até o Pix — sem WhatsApp e sem rede.
"""

from __future__ import annotations

from typing import Any

from app.agent.channels.base import InboundMessage


class ConsoleAdapter:
    """Implementa `ChannelAdapter` guardando as respostas numa lista."""

    name = "console"

    #: Teto do histórico: em modo falso este adapter é um singleton de processo
    #: e viveria para sempre acumulando mensagens.
    MAX_HISTORY = 500

    def __init__(self, echo: bool = False) -> None:
        #: Todas as respostas enviadas, na ordem: [(telefone, texto), ...]
        self.sent: list[tuple[str, str]] = []
        self._echo = echo

    async def send_text(self, to: str, text: str) -> str | None:
        self.sent.append((to, text))
        if len(self.sent) > self.MAX_HISTORY:
            del self.sent[: -self.MAX_HISTORY]
        if self._echo:
            print(text)
        return None

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Aceita o formato simples do simulador: {"phone": ..., "text": ...}."""
        phone = payload.get("phone")
        text = payload.get("text")
        if not phone or not text:
            return []
        return [InboundMessage(phone=str(phone), text=str(text), raw=payload)]

    # -- utilidades de teste ------------------------------------------------

    def replies_for(self, phone: str) -> list[str]:
        return [text for to, text in self.sent if to == phone]

    def drain(self) -> list[str]:
        """Devolve e limpa o que foi enviado desde a última leitura."""
        texts = [text for _, text in self.sent]
        self.sent.clear()
        return texts
