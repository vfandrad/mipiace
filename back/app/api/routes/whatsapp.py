"""Webhook do WhatsApp Cloud API.

Duas regras da Meta moldam este arquivo:

1. O `GET` precisa devolver o `hub.challenge` como **texto puro** para o número
   ser verificado.
2. O `POST` precisa responder 200 rápido, mesmo se o processamento falhar — a
   Meta reenvia o evento de forma agressiva e acaba desativando o webhook.
   Por isso o corpo é processado dentro de um try/except abrangente.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.channels.whatsapp import WhatsAppCloudAdapter
from app.agent.runner import handle_inbound
from app.core.config import get_settings
from app.db.session import get_sessionmaker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/whatsapp", tags=["webhooks"])


@router.get("", response_class=PlainTextResponse)
async def verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Desafio de verificação do número na Meta."""
    settings = get_settings()
    expected = settings.whatsapp_verify_token

    if hub_mode == "subscribe" and hub_verify_token and hmac.compare_digest(
        hub_verify_token, expected
    ):
        return PlainTextResponse(hub_challenge or "", status_code=status.HTTP_200_OK)

    logger.warning("verificação do webhook recusada (mode=%s)", hub_mode)
    return PlainTextResponse("forbidden", status_code=status.HTTP_403_FORBIDDEN)


def _signature_ok(body: bytes, header: str | None) -> bool:
    """HMAC-SHA256 do corpo cru com o app secret, comparado em tempo constante."""
    settings = get_settings()
    secret = settings.whatsapp_app_secret

    if not secret:
        if settings.fake_mode:
            logger.warning(
                "WHATSAPP_APP_SECRET ausente: assinatura NÃO validada (fake_mode)."
            )
            return True
        logger.error("WHATSAPP_APP_SECRET ausente em produção; rejeitando webhook")
        return False

    if not header or not header.startswith("sha256="):
        return False

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.post("", status_code=status.HTTP_200_OK)
async def receive(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    """Recebe mensagens do WhatsApp e roda o agente para cada uma."""
    body = await request.body()

    if not _signature_ok(body, x_hub_signature_256):
        # 200 mesmo assim: assinatura inválida costuma ser ruído, e um 4xx aqui
        # faz a Meta reenviar sem parar.
        logger.warning("assinatura do webhook inválida; evento descartado")
        return {"status": "ignored"}

    try:
        payload = await request.json()
    except Exception:
        logger.warning("payload do webhook não é JSON válido")
        return {"status": "ignored"}

    try:
        messages = WhatsAppCloudAdapter(get_settings()).parse_webhook(payload)
    except Exception:
        logger.exception("payload do webhook em formato inesperado")
        return {"status": "ignored"}

    if not messages:
        return {"status": "ok"}

    sessionmaker = get_sessionmaker()
    for message in messages:
        try:
            async with sessionmaker() as db:  # type: AsyncSession
                await handle_inbound(db, message, channel_name="whatsapp")
                await db.commit()
        except Exception:
            # Uma mensagem com problema não pode impedir as outras nem virar 500.
            logger.exception("falha ao processar mensagem de %s", message.phone)

    return {"status": "ok"}
