"""Canal WhatsApp via Evolution API (gateway self-hosted, Baileys por baixo).

Alternativa à WhatsApp Cloud API da Meta para desenvolvimento: não exige app
comercial aprovado, só parear um QR code. Duas diferenças relevantes em
relação ao `WhatsAppCloudAdapter`:

1. O payload do webhook é o evento `messages.upsert` do Baileys, bem mais raso
   que o da Meta (`data` já é a mensagem, sem `entry[].changes[].value`).
2. Evolution API não assina o corpo do webhook — por isso a validação, feita
   na rota (`app/api/routes/evolution.py`), é um token compartilhado na query
   string, não HMAC.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.agent.channels.base import InboundMessage
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


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
            "Content-Type": "application/json",
        }

        try:
            if self._client is not None:
                response = await self._client.post(self._send_url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(self._send_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except Exception:
            # Falha de envio não pode derrubar o processamento do webhook.
            logger.exception("falha ao enviar mensagem para %s via Evolution API", to)
            return None

        return (data.get("key") or {}).get("id")

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
