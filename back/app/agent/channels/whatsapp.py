"""Canal WhatsApp Cloud API (Meta).

Duas responsabilidades: mandar texto para o Graph API e desembrulhar o payload
do webhook, que vem bem aninhado (`entry[].changes[].value.messages[]`) e
misturado com eventos de status de entrega — que precisam ser ignorados, senão
o bot responde ao próprio "lido".
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.agent.channels.base import InboundMessage
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.facebook.com"


class WhatsAppCloudAdapter:
    """Implementa `ChannelAdapter` para a Cloud API do WhatsApp."""

    name = "whatsapp"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    @property
    def _url(self) -> str:
        version = self._settings.whatsapp_api_version
        phone_id = self._settings.whatsapp_phone_number_id
        return f"{GRAPH_BASE_URL}/{version}/{phone_id}/messages"

    async def send_text(self, to: str, text: str) -> str | None:
        """Envia texto e devolve o id da mensagem na Meta (ou None se falhou)."""
        if not self._settings.whatsapp_token or not self._settings.whatsapp_phone_number_id:
            logger.warning("WhatsApp não configurado; mensagem não enviada para %s", to)
            return None

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        headers = {
            "Authorization": f"Bearer {self._settings.whatsapp_token}",
            "Content-Type": "application/json",
        }

        try:
            if self._client is not None:
                response = await self._client.post(self._url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(self._url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except Exception:
            # Falha de envio não pode derrubar o processamento do webhook.
            logger.exception("falha ao enviar mensagem para %s", to)
            return None

        messages = data.get("messages") or []
        return messages[0].get("id") if messages else None

    # -- webhook -----------------------------------------------------------

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Extrai só mensagens de TEXTO; ignora status, reações e mídia."""
        messages: list[InboundMessage] = []

        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                if "messages" not in value:
                    continue  # evento de status (sent/delivered/read)

                profiles = self._profiles(value)
                for raw in value.get("messages") or []:
                    message = self._to_inbound(raw, profiles)
                    if message is not None:
                        messages.append(message)

        return messages

    @staticmethod
    def _profiles(value: dict[str, Any]) -> dict[str, str]:
        """`wa_id -> nome do perfil`, para já saber como chamar o cliente."""
        profiles: dict[str, str] = {}
        for contact in value.get("contacts") or []:
            wa_id = contact.get("wa_id")
            name = (contact.get("profile") or {}).get("name")
            if wa_id and name:
                profiles[wa_id] = name
        return profiles

    @staticmethod
    def _to_inbound(raw: dict[str, Any], profiles: dict[str, str]) -> InboundMessage | None:
        phone = raw.get("from")
        if not phone:
            return None

        text = WhatsAppCloudAdapter._text_of(raw)
        if not text:
            logger.info("mensagem sem texto ignorada (tipo=%s)", raw.get("type"))
            return None

        return InboundMessage(
            phone=str(phone),
            text=text,
            provider_message_id=raw.get("id"),
            profile_name=profiles.get(str(phone)),
            timestamp=WhatsAppCloudAdapter._timestamp(raw.get("timestamp")),
            raw=raw,
        )

    @staticmethod
    def _text_of(raw: dict[str, Any]) -> str | None:
        """Texto puro ou a resposta de um botão/lista interativa."""
        kind = raw.get("type")
        if kind == "text":
            return (raw.get("text") or {}).get("body")
        if kind == "interactive":
            interactive = raw.get("interactive") or {}
            for key in ("button_reply", "list_reply"):
                reply = interactive.get(key) or {}
                if reply.get("title"):
                    return reply["title"]
        if kind == "button":
            return (raw.get("button") or {}).get("text")
        return None

    @staticmethod
    def _timestamp(raw: Any) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        except (TypeError, ValueError):
            return None
