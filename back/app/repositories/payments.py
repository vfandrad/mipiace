"""Acesso a dados de pagamentos e de eventos de webhook."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, WebhookEvent
from app.domain.enums import PaymentStatus


async def get_payment(session: AsyncSession, payment_id: UUID) -> Payment | None:
    return await session.get(Payment, payment_id)


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


__all__ = [
    "claim_webhook_event",
    "create_payment",
    "get_latest_payment",
    "get_payment",
    "get_payment_by_provider_id",
    "mark_event_processed",
]
