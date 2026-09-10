"""Webhook do Mercado Pago.

Três garantias que este arquivo precisa dar:
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

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.logging import get_logger
from app.repositories import payments as payments_repo
from app.services import orders as orders_service
from app.services.payments.factory import get_payment_provider

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SOURCE = "mercadopago"


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

    event = await payments_repo.claim_webhook_event(
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
        order, approved_now = await orders_service.apply_payment_result(
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

    await payments_repo.mark_event_processed(session, event)
    await session.commit()

    if order is not None and approved_now:
        await orders_service.notify_agent_payment_approved(session, order.id)

    return {"status": "ok", "pedido": order.code if order else ""}


@router.get("/mercadopago")
async def mercadopago_probe() -> Response:
    """O MP faz um GET de teste ao cadastrar a URL."""
    return Response(status_code=status.HTTP_200_OK)
