"""Rotas de desenvolvimento — só existem com FAKE_MODE=true.

É o que substitui "abrir o app do banco e pagar o Pix" no teste local: aprova
a cobrança falsa e dispara exatamente o mesmo caminho do webhook real, agente
notificado inclusive.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, bad_request, not_found, require_fake_mode
from app.schemas.order import OrderSummary
from app.services import orders as orders_service
from app.services.payments.factory import get_payment_provider
from app.services.payments.fake import FakePaymentProvider

router = APIRouter(
    prefix="/api/dev", tags=["dev"], dependencies=[Depends(require_fake_mode)]
)


@router.post("/payments/{order_id}/approve", response_model=OrderSummary)
async def approve_fake_payment(order_id: UUID, session: SessionDep) -> OrderSummary:
    """Aprova o Pix falso do pedido e roda a mesma rotina do webhook."""
    provider = get_payment_provider()
    if not isinstance(provider, FakePaymentProvider):
        raise bad_request("Provedor de pagamento real não pode ser aprovado à mão.")

    payment = await orders_service.get_pending_payment(session, order_id)
    if payment is None or not payment.provider_payment_id:
        raise not_found("Nenhuma cobrança Pix pendente para este pedido.")

    provider.approve(payment.provider_payment_id)
    result = await provider.get_payment(payment.provider_payment_id)
    order, approved_now = await orders_service.apply_payment_result(
        session, result, provider_name=provider.name
    )
    if order is None:
        raise not_found("Pedido não encontrado.")
    if approved_now:
        await orders_service.notify_agent_payment_approved(session, order.id)

    summary = await orders_service.get_order_summary(session, order.id)
    if summary is None:  # pragma: no cover - o pedido acabou de ser lido
        raise not_found("Pedido não encontrado.")
    return summary
