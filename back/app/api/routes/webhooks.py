"""Webhooks — as duas portas de entrada que o mundo externo usa.

`/webhooks/evolution` recebe as mensagens do WhatsApp; `/webhooks/mercadopago`
recebe a confirmação do Pix. Nenhuma das duas exige `X-API-Key`: cada uma
valida o próprio remetente (token na query string e HMAC, respectivamente).

Três garantias que o webhook de pagamento precisa dar:
  1. **Idempotência** — a mesma notificação chega várias vezes; a tabela
     `webhook_events` (UNIQUE source+external_id) é quem decide se já foi.
  2. **Nunca confiar no payload** — o corpo só diz *qual* pagamento mudou; o
     status vem de uma consulta à API do provedor.
  3. **Nunca derrubar por causa do agente** — se avisar o cliente falhar, o
     pagamento continua registrado.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.agent.whatsapp import EvolutionAdapter
from app.agent.runner import handle_inbound, handle_outbound_echo
from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.services import payments as payments_service
from app.services.pix_provider import get_payment_provider

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SOURCE = "mercadopago"


# ---------------------------------------------------------------------------
# WhatsApp (Evolution API)
# ---------------------------------------------------------------------------

def _evolution_token_ok(token: str | None) -> bool:
    """Evolution API não assina o corpo: a validação é um token na query string.

    O token vem cadastrado na própria URL que a Evolution chama
    (WEBHOOK_GLOBAL_URL no docker-compose.yml).
    """
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


@router.post("/evolution", status_code=status.HTTP_200_OK)
async def evolution_webhook(
    request: Request,
    token: str | None = Query(default=None),
) -> dict[str, str]:
    """Recebe eventos da Evolution API e roda o agente para cada mensagem."""
    if not _evolution_token_ok(token):
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

    sessionmaker = get_sessionmaker()
    for message in messages:
        try:
            async with sessionmaker() as db:
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


# ---------------------------------------------------------------------------
# Pagamento (Mercado Pago)
# ---------------------------------------------------------------------------


def _extract_payment_id(body: dict[str, Any], query: dict[str, str]) -> str | None:
    """O MP manda o id ora no corpo, ora na query (`data.id`)."""
    data = body.get("data") or {}
    candidate = (
        data.get("id")
        or query.get("data.id")
        or query.get("id")
        or body.get("resource")
    )
    if candidate is None:
        return None
    # Notificações antigas mandam a URL inteira em "resource".
    return str(candidate).rstrip("/").split("/")[-1]


def _event_topic(body: dict[str, Any], query: dict[str, str]) -> str:
    return str(
        body.get("type") or body.get("topic") or query.get("type") or query.get("topic") or ""
    ).lower()


def _event_id(body: dict[str, Any], payment_id: str | None) -> str:
    """Id do evento: o do MP quando existe, senão tópico+ação+pagamento."""
    if body.get("id") is not None:
        return str(body["id"])
    action = body.get("action") or body.get("type") or "payment"
    return f"{action}:{payment_id}"


def _valid_signature(request: Request, payment_id: str | None) -> bool:
    """Valida `x-signature` no formato ts=...,v1=... (HMAC-SHA256).

    Sem `MP_WEBHOOK_SECRET` configurado a validação é pulada — o segredo é
    opcional na conta do MP e travar aqui deixaria o MVP sem webhook.
    """
    secret = get_settings().mp_webhook_secret
    if not secret:
        return True

    signature = request.headers.get("x-signature", "")
    parts = dict(
        piece.strip().split("=", 1) for piece in signature.split(",") if "=" in piece
    )
    ts, received = parts.get("ts"), parts.get("v1")
    if not ts or not received:
        return False

    request_id = request.headers.get("x-request-id", "")
    manifest = f"id:{payment_id};request-id:{request_id};ts:{ts};"
    expected = hmac.new(
        secret.encode(), manifest.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, received)


@router.post("/mercadopago")
async def mercadopago_webhook(request: Request, session: SessionDep) -> dict[str, str]:
    raw = await request.body()
    try:
        body: dict[str, Any] = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {}
    query = dict(request.query_params)

    topic = _event_topic(body, query)
    payment_id = _extract_payment_id(body, query)

    if not _valid_signature(request, payment_id):
        logger.warning("Assinatura inválida no webhook do Mercado Pago.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura inválida."
        )

    # Só pagamento interessa; o resto (merchant_order, plan...) é descartado com 200
    # para o MP não ficar reenviando.
    if topic and "payment" not in topic:
        return {"status": "ignorado"}
    if not payment_id:
        return {"status": "sem_id"}

    event = await payments_service.claim_webhook_event(
        session, source=SOURCE, external_id=_event_id(body, payment_id), payload=body
    )
    if event is None:
        logger.info("Evento repetido do Mercado Pago ignorado (%s).", payment_id)
        return {"status": "duplicado"}
    await session.commit()

    try:
        # get_payment_provider() também pode falhar (ex.: MP_ACCESS_TOKEN
        # ausente); precisa estar dentro do try para liberar o "claim" acima.
        provider = get_payment_provider()
        # Fonte da verdade é a API, nunca o corpo do webhook.
        result = await provider.get_payment(payment_id)
        order, approved_now = await payments_service.apply_payment_result(
            session, result, provider_name=provider.name
        )
    except Exception as exc:  # noqa: BLE001
        # Solta o "claim" para o MP poder reenviar e a gente reprocessar.
        await session.rollback()
        await session.delete(event)
        await session.commit()
        logger.exception("Falha ao processar pagamento %s", payment_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível confirmar o pagamento no provedor.",
        ) from exc

    await payments_service.mark_event_processed(session, event)
    await session.commit()

    if order is not None and approved_now:
        await payments_service.notify_agent_payment_approved(session, order.id)

    return {"status": "ok", "pedido": order.code if order else ""}


@router.get("/mercadopago")
async def mercadopago_probe() -> Response:
    """O MP faz um GET de teste ao cadastrar a URL."""
    return Response(status_code=status.HTTP_200_OK)
