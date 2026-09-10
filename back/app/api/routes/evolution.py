"""Webhook da Evolution API (gateway WhatsApp self-hosted).

Evolution API não assina o corpo do webhook do jeito que a Meta faz (sem
X-Hub-Signature). A validação aqui é um token compartilhado na query string,
configurado em EVOLUTION_WEBHOOK_TOKEN e cadastrado na própria URL que a
Evolution API chama (WEBHOOK_GLOBAL_URL no docker-compose.yml).
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.channels.evolution import EvolutionAdapter
from app.agent.runner import handle_inbound, handle_outbound_echo
from app.core.config import get_settings
from app.db.session import get_sessionmaker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/evolution", tags=["webhooks"])


def _token_ok(token: str | None) -> bool:
    settings = get_settings()
    expected = settings.evolution_webhook_token

    if not expected:
        if settings.fake_mode:
            logger.warning(
                "EVOLUTION_WEBHOOK_TOKEN ausente: token NÃO validado (fake_mode)."
            )
            return True
        logger.error("EVOLUTION_WEBHOOK_TOKEN ausente em produção; rejeitando webhook")
        return False

    return bool(token) and hmac.compare_digest(token, expected)


@router.post("", status_code=status.HTTP_200_OK)
async def receive(
    request: Request,
    token: str | None = Query(default=None),
) -> dict[str, str]:
    """Recebe eventos da Evolution API e roda o agente para cada mensagem."""
    if not _token_ok(token):
        logger.warning("token do webhook da Evolution API inválido; evento descartado")
        return {"status": "ignored"}

    try:
        payload = await request.json()
    except Exception:
        logger.warning("payload do webhook da Evolution API não é JSON válido")
        return {"status": "ignored"}

    try:
        messages = EvolutionAdapter(get_settings()).parse_webhook(payload)
    except Exception:
        logger.exception("payload do webhook da Evolution API em formato inesperado")
        return {"status": "ignored"}

    if not messages:
        return {"status": "ok"}

    sessionmaker = get_sessionmaker()
    for message in messages:
        try:
            async with sessionmaker() as db:  # type: AsyncSession
                if message.from_me:
                    # Eco do bot ou resposta manual do lojista: só histórico,
                    # nunca aciona IA/máquina de estados.
                    await handle_outbound_echo(db, message, channel_name="whatsapp")
                else:
                    await handle_inbound(db, message, channel_name="whatsapp")
                await db.commit()
        except Exception:
            # Uma mensagem com problema não pode impedir as outras nem virar 500.
            logger.exception("falha ao processar mensagem de %s", message.phone)

    return {"status": "ok"}
