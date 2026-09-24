"""Ciclo de vida do pagamento Pix: criar a cobrança e aplicar o resultado.

Separado de `orders.py` porque é a parte do pedido que conversa com o mundo
externo (o provedor de Pix e o webhook), enquanto lá ficam as regras do pedido
em si. A regra de ouro está em `apply_payment_result`: o status vem sempre de
uma consulta ao provedor, nunca do corpo do webhook.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Order, Payment, WebhookEvent
from app.domain.cart import money
from app.domain.enums import OrderStatus, PaymentStatus
from app.services.orders import OrderError, OrderNotFoundError, get_order
from app.services.pix_provider import (
    PaymentStatusResult,
    PixCharge,
    get_payment_provider,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Acesso a dados
# ---------------------------------------------------------------------------


async def get_payment_by_provider_id(
    session: AsyncSession, *, provider: str, provider_payment_id: str
) -> Payment | None:
    return await session.scalar(
        select(Payment).where(
            Payment.provider == provider,
            Payment.provider_payment_id == provider_payment_id,
        )
    )


async def get_latest_payment(
    session: AsyncSession,
    order_id: UUID,
    *,
    status: PaymentStatus | None = None,
) -> Payment | None:
    stmt = (
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    if status is not None:
        stmt = stmt.where(Payment.status == status)
    return await session.scalar(stmt)


async def create_payment(session: AsyncSession, data: dict[str, Any]) -> Payment:
    payment = Payment(**data)
    session.add(payment)
    await session.flush()
    return payment


async def claim_webhook_event(
    session: AsyncSession,
    *,
    source: str,
    external_id: str,
    payload: dict[str, Any],
) -> WebhookEvent | None:
    """Registra o evento e devolve None se ele já tinha sido registrado.

    A idempotência é do banco (UNIQUE source+external_id) e não da aplicação:
    o Mercado Pago reenvia a mesma notificação e duas réplicas do backend
    podem recebê-la ao mesmo tempo.
    """
    stmt = (
        pg_insert(WebhookEvent)
        .values(source=source, external_id=external_id, payload=payload)
        .on_conflict_do_nothing(constraint="uq_webhook_event")
        .returning(WebhookEvent.id)
    )
    inserted_id = await session.scalar(stmt)
    if inserted_id is None:
        return None
    return await session.get(WebhookEvent, inserted_id)


async def mark_event_processed(
    session: AsyncSession, event: WebhookEvent, *, error: str | None = None
) -> None:
    event.processed_at = datetime.now(timezone.utc)
    event.error = error
    await session.flush()

# ---------------------------------------------------------------------------
# Cobrança e confirmação
# ---------------------------------------------------------------------------


async def create_pix_for_order(session: AsyncSession, order_id: UUID) -> PixCharge:
    """Cria (ou reaproveita) a cobrança Pix do pedido.

    Reaproveitar a cobrança pendente evita gerar dois QR para o mesmo pedido
    quando o cliente pede o código de novo.
    """
    order = await get_order(session, order_id)
    if order is None:
        raise OrderNotFoundError(f"Pedido {order_id} não encontrado.")
    if order.payment_status is PaymentStatus.PAGO:
        raise OrderError("Pedido já está pago.")

    provider = get_payment_provider()

    existing = await get_latest_payment(
        session, order_id, status=PaymentStatus.PENDENTE
    )
    if existing is not None and existing.provider == provider.name and existing.qr_code:
        return PixCharge(
            provider=existing.provider,
            provider_payment_id=existing.provider_payment_id or "",
            amount=existing.amount,
            qr_code=existing.qr_code,
            qr_code_base64=existing.qr_code_base64,
            ticket_url=existing.ticket_url,
            expires_at=existing.expires_at,
            raw=existing.raw_payload or {},
        )

    charge = await provider.create_pix_charge(
        order_id=order.id,
        order_code=order.code,
        amount=order.total,
        payer_name=order.customer.name if order.customer else None,
        payer_phone=order.customer.phone if order.customer else None,
    )

    await create_payment(
        session,
        {
            "order_id": order.id,
            "provider": charge.provider,
            "provider_payment_id": charge.provider_payment_id,
            "method": "pix",
            "amount": money(charge.amount),
            "status": PaymentStatus.PENDENTE,
            "qr_code": charge.qr_code,
            "qr_code_base64": charge.qr_code_base64,
            "ticket_url": charge.ticket_url,
            "expires_at": charge.expires_at,
            "raw_payload": charge.raw or None,
        },
    )
    await session.flush()
    logger.info("Pix criado para %s (%s)", order.code, charge.provider_payment_id)
    return charge


async def apply_payment_result(
    session: AsyncSession, result: PaymentStatusResult, *, provider_name: str
) -> tuple[Order | None, bool]:
    """Aplica ao banco o status consultado no provedor.

    Devolve `(pedido, aprovado_agora)`. `aprovado_agora` é False quando o
    pedido já estava pago — é o que impede o webhook de notificar o cliente
    duas vezes.
    """
    payment = await get_payment_by_provider_id(
        session,
        provider=provider_name,
        provider_payment_id=result.provider_payment_id,
    )
    order: Order | None = None
    if payment is not None:
        order = await get_order(session, payment.order_id)
    elif result.external_reference:
        # Cobrança criada fora do nosso fluxo: ainda dá para achar o pedido.
        try:
            order = await get_order(session, UUID(result.external_reference))
        except ValueError:
            order = None

    if order is None:
        logger.warning(
            "Pagamento %s sem pedido correspondente", result.provider_payment_id
        )
        return None, False

    if payment is not None:
        payment.status = result.status
        payment.raw_payload = result.raw or payment.raw_payload

    already_paid = order.payment_status is PaymentStatus.PAGO
    approved_now = result.status is PaymentStatus.PAGO and not already_paid

    if approved_now:
        order.payment_status = PaymentStatus.PAGO
        order.paid_at = datetime.now(timezone.utc)
        if order.status is OrderStatus.NOVO:
            # Pagou, entra na fila da produção.
            order.status = OrderStatus.PREPARANDO
    elif result.status in {PaymentStatus.EXPIRADO, PaymentStatus.CANCELADO}:
        if not already_paid:
            order.payment_status = result.status

    await session.flush()
    return order, approved_now


async def notify_agent_payment_approved(session: AsyncSession, order_id: UUID) -> None:
    """Avisa o agente que o Pix caiu — sem deixar o webhook morrer por isso.

    Import tardio de propósito: `app.agent.runner` importa serviços daqui, e o
    ciclo quebraria o boot. Se o agente ainda não existir (desenvolvimento em
    paralelo), o pagamento continua registrado.
    """
    try:
        from app.agent.runner import notify_payment_approved  # noqa: PLC0415
    except ImportError:  # pragma: no cover - agente opcional
        logger.warning("app.agent.runner indisponível; cliente não foi notificado.")
        return
    try:
        await notify_payment_approved(session, order_id)
        # ÚNICA exceção à regra "quem comita é a rota": esta função é chamada
        # DEPOIS do commit da rota, já fora do fluxo de resposta, e escreve o
        # novo estado da conversa. Sem o commit aqui a conversa fica presa em
        # "aguardando_pagamento" e o cliente nunca recebe a confirmação.
        await session.commit()
    except Exception:  # noqa: BLE001 - notificação nunca derruba o webhook
        logger.exception("Falha ao notificar o cliente do pedido %s", order_id)
        await session.rollback()


async def get_pending_payment(session: AsyncSession, order_id: UUID) -> Payment | None:
    """Cobrança Pix pendente do pedido, se houver."""
    return await get_latest_payment(
        session, order_id, status=PaymentStatus.PENDENTE
    )


__all__ = [
    "apply_payment_result",
    "create_pix_for_order",
    "get_pending_payment",
    "notify_agent_payment_approved",
]
