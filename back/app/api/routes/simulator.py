"""Simulador de conversa — testar o agente inteiro sem WhatsApp e sem Pix real.

Só existe com `FAKE_MODE=true`. Em produção qualquer chamada aqui devolve 404:
seria um jeito de escrever no estado de conversas reais e de aprovar cobranças
à mão. Como todo o resto de `/api`, exige `X-API-Key` (montado em `main.py`).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agent.runner import handle_inbound
from app.agent.session import load_or_create, reset_session
from app.agent.whatsapp import InboundMessage
from app.api.deps import SessionDep, bad_request, not_found, require_fake_mode
from app.schemas.order import OrderSummary
from app.services import orders as orders_service
from app.services import payments as payments_service
from app.services.pix_provider import FakePaymentProvider, get_payment_provider

router = APIRouter(
    prefix="/api/simulator",
    tags=["simulador"],
    dependencies=[Depends(require_fake_mode)],
)

CHANNEL = "simulador"


class SimulatorMessage(BaseModel):
    phone: str = Field(min_length=3, max_length=32)
    text: str = Field(min_length=1, max_length=2000)


class SimulatorReply(BaseModel):
    replies: list[str]
    state: str


class SimulatorReset(BaseModel):
    phone: str = Field(min_length=3, max_length=32)


@router.post("/message", response_model=SimulatorReply)
async def send_message(payload: SimulatorMessage, db: SessionDep) -> SimulatorReply:
    """Manda uma mensagem como se fosse o cliente e devolve o que o bot diria."""
    message = InboundMessage(phone=payload.phone, text=payload.text)
    replies = await handle_inbound(db, message, channel_name=CHANNEL)
    conversation = await load_or_create(db, payload.phone, CHANNEL)
    await db.commit()

    return SimulatorReply(replies=replies, state=conversation.state.value)


@router.post("/reset", response_model=SimulatorReply)
async def reset(payload: SimulatorReset, db: SessionDep) -> SimulatorReply:
    """Volta a conversa para o início e apaga o histórico de mensagens."""
    conversation = await reset_session(db, payload.phone, CHANNEL)
    await db.commit()
    return SimulatorReply(replies=[], state=conversation.state.value)


@router.post("/payments/{order_id}/approve", response_model=OrderSummary)
async def approve_fake_payment(order_id: UUID, session: SessionDep) -> OrderSummary:
    """Aprova o Pix falso do pedido e roda a mesma rotina do webhook real.

    É o que substitui "abrir o app do banco e pagar o Pix" no teste local:
    dispara exatamente o mesmo caminho, agente notificado inclusive.
    """
    provider = get_payment_provider()
    if not isinstance(provider, FakePaymentProvider):
        raise bad_request("Provedor de pagamento real não pode ser aprovado à mão.")

    payment = await payments_service.get_pending_payment(session, order_id)
    if payment is None or not payment.provider_payment_id:
        raise not_found("Nenhuma cobrança Pix pendente para este pedido.")

    provider.approve(payment.provider_payment_id)
    result = await provider.get_payment(payment.provider_payment_id)
    order, approved_now = await payments_service.apply_payment_result(
        session, result, provider_name=provider.name
    )
    await session.commit()
    if order is None:
        raise not_found("Pedido não encontrado.")
    if approved_now:
        await payments_service.notify_agent_payment_approved(session, order.id)

    summary = await orders_service.get_order_summary(session, order.id)
    if summary is None:  # pragma: no cover - o pedido acabou de ser lido
        raise not_found("Pedido não encontrado.")
    return summary
