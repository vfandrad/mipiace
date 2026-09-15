"""Canais de mensagem do agente — para onde as respostas vão.

São dois, e o `FAKE_MODE` decide qual:

* `EvolutionAdapter` — WhatsApp de verdade, via Evolution API (gateway
  self-hosted, Baileys por baixo). Não exige app comercial aprovado, só parear
  um QR code. O webhook dele é o evento `messages.upsert`: `data` já é a
  mensagem, sem os envelopes de outros provedores. A Evolution API não assina o
  corpo do webhook — a validação, feita em `api/routes/webhooks.py`, é um token
  compartilhado na query string.
* `ConsoleAdapter` — canal em memória. Serve o simulador HTTP, a CLI e os
  testes; é ele que permite exercitar a conversa inteira, de "oi" até o Pix,
  sem WhatsApp e sem rede.

A máquina de estados não sabe qual dos dois está atrás: ela só entrega texto
para um `ChannelAdapter`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Contrato
# ---------------------------------------------------------------------------

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
    """Implementado por EvolutionAdapter e ConsoleAdapter."""

    name: str

    async def send_text(self, to: str, text: str) -> str | None:
        """Envia texto e devolve o id da mensagem no provedor, se houver."""
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Extrai as mensagens de um payload de webhook do provedor."""
        ...


# ---------------------------------------------------------------------------
# WhatsApp de verdade
# ---------------------------------------------------------------------------

class EvolutionAdapter:
    """Implementa `ChannelAdapter` para a Evolution API."""

    name = "whatsapp"

    def __init__(
        self, settings: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client

    @property
    def _send_url(self) -> str:
        base = self._settings.evolution_api_url.rstrip("/")
        instance = self._settings.evolution_instance
        return f"{base}/message/sendText/{instance}"

    async def send_text(self, to: str, text: str) -> str | None:
        """Envia texto e devolve o id da mensagem na Evolution API (ou None se falhou)."""
        if not self._settings.evolution_api_key:
            logger.warning(
                "Evolution API não configurada; mensagem não enviada para %s", to
            )
            return None

        payload = {"number": to, "text": text}
        headers = {
            "apikey": self._settings.evolution_api_key,
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            if self._client is not None:
                response = await self._client.post(self._send_url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(self._send_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return (data.get("key") or {}).get("id")
        except httpx.HTTPStatusError as e:
            logger.error(
                "Evolution API erro %s ao enviar para %s: %s",
                e.response.status_code,
                to,
                e.response.text[:200] if e.response.text else "(sem corpo)",
            )
            raise
        except Exception as e:
            logger.exception("falha ao conectar com Evolution API para %s: %s", to, str(e))
            raise

    # -- webhook -----------------------------------------------------------

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Extrai mensagens de texto do evento `messages.upsert`; ignora o resto."""
        if payload.get("event") != "messages.upsert":
            return []

        data = payload.get("data")
        entries: list[Any] = data if isinstance(data, list) else [data] if data else []

        messages: list[InboundMessage] = []
        for raw in entries:
            message = self._to_inbound(raw or {})
            if message is not None:
                messages.append(message)
        return messages

    @staticmethod
    def _to_inbound(raw: dict[str, Any]) -> InboundMessage | None:
        key = raw.get("key") or {}
        remote_jid = key.get("remoteJid") or ""

        # Só processamos chat individual (sufixo "@s.whatsapp.net"). O número
        # ficou pareado com o WhatsApp da loja, então grupos (`@g.us`), listas
        # de transmissão/status (`@broadcast`) e canais (`@newsletter`) também
        # chegam como messages.upsert — sem esse filtro, qualquer mensagem de
        # terceiros num grupo viraria "pedido" (ou, no caso de fromMe, entraria
        # no histórico do painel como se fosse uma resposta 1:1).
        if not remote_jid.endswith("@s.whatsapp.net"):
            logger.info("mensagem fora de chat individual ignorada (jid=%s)", remote_jid)
            return None

        # remoteJid pode vir com sufixo de device multi-aparelho ("<numero>:<n>@...");
        # sem remover, o mesmo cliente vira duas conversas diferentes conforme o
        # aparelho usado.
        phone = remote_jid.split("@")[0].split(":")[0]
        if not phone:
            return None

        text = EvolutionAdapter._text_of(raw)
        if not text:
            logger.info("mensagem sem texto ignorada (jid=%s)", key.get("remoteJid"))
            return None

        return InboundMessage(
            phone=phone,
            text=text,
            provider_message_id=key.get("id"),
            profile_name=raw.get("pushName"),
            timestamp=EvolutionAdapter._timestamp(raw.get("messageTimestamp")),
            # fromMe = eco do bot ou resposta manual do lojista pelo celular.
            # Não descartamos mais: o runner trata separado (vira só histórico,
            # nunca aciona IA/máquina de estados) para o painel espelhar o chat
            # inteiro do número da loja, não só o que passou pelo bot.
            from_me=bool(key.get("fromMe")),
            raw=raw,
        )

    @staticmethod
    def _text_of(raw: dict[str, Any]) -> str | None:
        """Texto puro ou a resposta de um botão/lista interativa do Baileys."""
        message = raw.get("message") or {}
        if message.get("conversation"):
            return message["conversation"]

        extended = message.get("extendedTextMessage") or {}
        if extended.get("text"):
            return extended["text"]

        buttons_reply = message.get("buttonsResponseMessage") or {}
        if buttons_reply.get("selectedDisplayText"):
            return buttons_reply["selectedDisplayText"]

        list_reply = message.get("listResponseMessage") or {}
        single_select = list_reply.get("singleSelectReply") or {}
        return list_reply.get("title") or single_select.get("selectedRowId")

    @staticmethod
    def _timestamp(raw: Any) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        except (TypeError, ValueError):
            return None

# ---------------------------------------------------------------------------
# Canal em memória (FAKE_MODE, simulador, CLI e testes)
# ---------------------------------------------------------------------------

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

    def replies_for(self, phone: str) -> list[str]:
        """Usado pelos testes e pelo simulador para ler o que o bot respondeu."""
        return [text for to, text in self.sent if to == phone]


# ---------------------------------------------------------------------------
# Escolha do canal
# ---------------------------------------------------------------------------

#: Canal em memória compartilhado do processo — o simulador lê daqui.
_console = ConsoleAdapter()


@lru_cache
def get_channel_adapter(channel_name: str = "whatsapp") -> ChannelAdapter:
    """Adapter do canal pedido. Em FAKE_MODE tudo vai para o console."""
    if channel_name == "console" or get_settings().fake_mode:
        return _console

    return EvolutionAdapter(get_settings())
