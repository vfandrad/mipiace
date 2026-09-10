"""Regras de pedido: fechamento do carrinho, Pix e mudança de status.

Este módulo é a fronteira entre a conversa (carrinho em JSON) e o pedido real:
é aqui que o preço é congelado, o código curto é emitido e o cliente vira uma
entidade do banco. Nada disso pode depender do que o LLM devolveu.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Order, OrderItem, OrderItemComplement, Payment
from app.domain.cart import Cart
from app.domain.enums import FulfillmentType, OrderChannel, OrderStatus, PaymentStatus
from app.repositories import orders as orders_repo
from app.repositories import payments as payments_repo
from app.schemas.order import OrderCreated, OrderSummary, OrderSummaryItem
from app.services import customers as customers_service
from app.services import pricing
from app.services.payments.base import PaymentStatusResult, PixCharge
from app.services.payments.factory import get_payment_provider

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Erros de domínio (as rotas traduzem para HTTP)
# ---------------------------------------------------------------------------


class OrderError(RuntimeError):
    """Erro de regra de negócio de pedido."""


class EmptyCartError(OrderError):
    pass


class MissingAddressError(OrderError):
    pass


class OrderNotFoundError(OrderError):
    pass


class InvalidStatusTransition(OrderError):
    def __init__(self, origin: OrderStatus, destination: OrderStatus) -> None:
        super().__init__(f"Não dá para ir de '{origin}' para '{destination}'.")
        self.origin = origin
        self.destination = destination


# ---------------------------------------------------------------------------
# Transições de status do PEDIDO (o Kanban)
# ---------------------------------------------------------------------------
# Nada a ver com o estado da CONVERSA (app/agent/states.py): aqui é o fluxo
# físico do pedido dentro da loja.

ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NOVO: {OrderStatus.PREPARANDO, OrderStatus.CANCELADO},
    OrderStatus.PREPARANDO: {
        OrderStatus.ENTREGA,
        OrderStatus.FINALIZADO,  # retirada no balcão pula a entrega
        OrderStatus.CANCELADO,
    },
    OrderStatus.ENTREGA: {OrderStatus.FINALIZADO, OrderStatus.CANCELADO},
    OrderStatus.FINALIZADO: set(),
    OrderStatus.CANCELADO: set(),
}


def can_transition_order(origin: OrderStatus, destination: OrderStatus) -> bool:
    """Repetir o mesmo status é aceito (PATCH idempotente vindo do Kanban)."""
    if origin == destination:
        return True
    return destination in ORDER_TRANSITIONS.get(origin, set())


def assert_order_transition(origin: OrderStatus, destination: OrderStatus) -> None:
    if not can_transition_order(origin, destination):
        raise InvalidStatusTransition(origin, destination)


# ---------------------------------------------------------------------------
# Código curto do pedido
# ---------------------------------------------------------------------------

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_CODE_SPACE = 36**4
#: Primo coprimo com 36^4: embaralha a sequência sem gerar colisão (bijetivo),
#: para "#0001, #0002" não virar contador público de vendas.
_SCRAMBLE = 7919


def format_order_code(number: int) -> str:
    """Transforma o nextval da sequence num código curto tipo "#063Z"."""
    value = (number * _SCRAMBLE) % _CODE_SPACE
    digits = []
    for _ in range(4):
        value, remainder = divmod(value, 36)
        digits.append(_ALPHABET[remainder])
    return "#" + "".join(reversed(digits))


# ---------------------------------------------------------------------------
# Criação do pedido
# ---------------------------------------------------------------------------


async def create_order_from_cart(
    session: AsyncSession,
    *,
    cart: Cart,
    phone: str,
    customer_name: str | None,
    fulfillment_type: FulfillmentType,
    address: dict | None,
    channel: OrderChannel,
    notes: str | None = None,
) -> OrderCreated:
    """Fecha o carrinho num pedido persistido e devolve o essencial.

    Congela nome e preço de produto/complemento em cada item: se o lojista
    mudar a tabela amanhã, o histórico continua contando a verdade.
    """
    if cart.is_empty:
        raise EmptyCartError("Carrinho vazio — não há o que fechar.")

    customer = await customers_service.get_or_create_customer(
        session, phone=phone, name=customer_name
    )

    saved_address = None
    if fulfillment_type is FulfillmentType.ENTREGA:
        saved_address = await customers_service.save_address(
            session, customer_id=customer.id, address=address or {}
        )
        if saved_address is None:
            raise MissingAddressError(
                "Entrega exige rua, número e bairro."
            )

    breakdown = pricing.calculate_cart(cart, fulfillment_type=fulfillment_type)
    code = format_order_code(await orders_repo.next_code_number(session))

    order = Order(
        code=code,
        customer_id=customer.id,
        address_id=saved_address.id if saved_address else None,
        fulfillment_type=fulfillment_type,
        channel=channel,
        status=OrderStatus.NOVO,
        payment_status=PaymentStatus.PENDENTE,
        subtotal=breakdown.subtotal,
        delivery_fee=breakdown.delivery_fee,
        total=breakdown.total,
        notes=notes,
    )
    session.add(order)
    await session.flush()

    for cart_item in cart.items:
        item = OrderItem(
            order_id=order.id,
            product_id=cart_item.product_id,
            product_name_snapshot=cart_item.product_name,
            unit_base_price=pricing.money(cart_item.unit_base_price),
            quantity=cart_item.quantity,
            line_total=pricing.item_line_total(cart_item),
            details=cart_item.details,
        )
        session.add(item)
        await session.flush()
        for complement in cart_item.complements:
            session.add(
                OrderItemComplement(
                    order_item_id=item.id,
                    complement_id=complement.id,
                    complement_name_snapshot=complement.name,
                    extra_price_snapshot=pricing.money(complement.extra_price),
                )
            )

    await session.commit()
    logger.info("Pedido %s criado (%s) total=%s", order.code, channel, order.total)

    return OrderCreated(
        id=order.id,
        code=order.code,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        total=order.total,
        status=order.status,
        payment_status=order.payment_status,
    )


# ---------------------------------------------------------------------------
# Pix
# ---------------------------------------------------------------------------


async def create_pix_for_order(session: AsyncSession, order_id: UUID) -> PixCharge:
    """Cria (ou reaproveita) a cobrança Pix do pedido.

    Reaproveitar a cobrança pendente evita gerar dois QR para o mesmo pedido
    quando o cliente pede o código de novo.
    """
    order = await orders_repo.get_order(session, order_id)
    if order is None:
        raise OrderNotFoundError(f"Pedido {order_id} não encontrado.")
    if order.payment_status is PaymentStatus.PAGO:
        raise OrderError("Pedido já está pago.")

    provider = get_payment_provider()

    existing = await payments_repo.get_latest_payment(
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

    await payments_repo.create_payment(
        session,
        {
            "order_id": order.id,
            "provider": charge.provider,
            "provider_payment_id": charge.provider_payment_id,
            "method": "pix",
            "amount": pricing.money(charge.amount),
            "status": PaymentStatus.PENDENTE,
            "qr_code": charge.qr_code,
            "qr_code_base64": charge.qr_code_base64,
            "ticket_url": charge.ticket_url,
            "expires_at": charge.expires_at,
            "raw_payload": charge.raw or None,
        },
    )
    await session.commit()
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
    payment = await payments_repo.get_payment_by_provider_id(
        session,
        provider=provider_name,
        provider_payment_id=result.provider_payment_id,
    )
    order: Order | None = None
    if payment is not None:
        order = await orders_repo.get_order(session, payment.order_id)
    elif result.external_reference:
        # Cobrança criada fora do nosso fluxo: ainda dá para achar o pedido.
        try:
            order = await orders_repo.get_order(session, UUID(result.external_reference))
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

    await session.commit()
    return order, approved_now


async def notify_agent_payment_approved(session: AsyncSession, order_id: UUID) -> None:
    """Avisa o agente que o Pix caiu — sem deixar o webhook morrer por isso.

    Import tardio de propósito: `app.agent.runner` importa serviços daqui, e o
    ciclo quebraria o boot. Se o agente ainda não existir (desenvolvimento em
    paralelo), o pagamento continua registrado.
    """
    try:
        from app.agent.runner import notify_payment_approved
    except ImportError:  # pragma: no cover - agente opcional
        logger.warning("app.agent.runner indisponível; cliente não foi notificado.")
        return
    try:
        await notify_payment_approved(session, order_id)
        # A camada do agente não comita de propósito — quem chama é que decide
        # a transação. Nas rotas de conversa quem comita é a própria rota; aqui
        # o chamador é o fluxo de pagamento, então o commit tem de ser nosso.
        # Sem ele, a conversa fica presa em "aguardando_pagamento" e o cliente
        # nunca recebe a confirmação do Pix.
        await session.commit()
    except Exception:  # noqa: BLE001 - notificação nunca derruba o webhook
        logger.exception("Falha ao notificar o cliente do pedido %s", order_id)
        await session.rollback()


# ---------------------------------------------------------------------------
# Status e leitura
# ---------------------------------------------------------------------------


async def update_order_status(
    session: AsyncSession, order_id: UUID, new_status: OrderStatus
) -> Order:
    order = await orders_repo.get_order(session, order_id)
    if order is None:
        raise OrderNotFoundError(f"Pedido {order_id} não encontrado.")

    assert_order_transition(order.status, new_status)
    if order.status == new_status:
        return order

    order.status = new_status
    if new_status is OrderStatus.CANCELADO:
        order.cancelled_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info("Pedido %s -> %s", order.code, new_status)
    return order


def _summary_item(item: OrderItem) -> OrderSummaryItem:
    unit_price = pricing.item_unit_price(
        item.unit_base_price, (c.extra_price_snapshot for c in item.complements)
    )
    return OrderSummaryItem(
        product_name=item.product_name_snapshot,
        quantity=item.quantity,
        complements=[c.complement_name_snapshot for c in item.complements],
        unit_price=unit_price,
        line_total=item.line_total,
        details=item.details,
    )


async def get_order_summary(
    session: AsyncSession, order_id: UUID
) -> OrderSummary | None:
    """Resumo pronto para o agente ler em voz alta para o cliente."""
    order = await orders_repo.get_order(session, order_id)
    if order is None:
        return None

    pending = await payments_repo.get_latest_payment(
        session, order.id, status=PaymentStatus.PENDENTE
    )
    return OrderSummary(
        id=order.id,
        code=order.code,
        status=order.status,
        payment_status=order.payment_status,
        fulfillment_type=order.fulfillment_type,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        total=order.total,
        items=[_summary_item(item) for item in order.items],
        customer_name=order.customer.name if order.customer else None,
        customer_phone=order.customer.phone if order.customer else None,
        address_line=customers_service.format_address(order.address),
        notes=order.notes,
        created_at=order.created_at,
        paid_at=order.paid_at,
        pix_qr_code=pending.qr_code if pending else None,
    )


async def list_orders(
    session: AsyncSession,
    *,
    status: OrderStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Order]:
    return await orders_repo.list_orders(
        session, status=status, limit=limit, offset=offset
    )


async def get_pending_payment(session: AsyncSession, order_id: UUID) -> Payment | None:
    return await payments_repo.get_latest_payment(
        session, order_id, status=PaymentStatus.PENDENTE
    )


def cart_from_json(raw: Any) -> Cart:
    """Converte o JSONB de `conversations.cart` em `Cart` (aceita lista ou dict)."""
    if isinstance(raw, list):
        return Cart(items=raw)
    if isinstance(raw, dict):
        return Cart.model_validate(raw)
    return Cart()


__all__ = [
    "EmptyCartError",
    "InvalidStatusTransition",
    "MissingAddressError",
    "ORDER_TRANSITIONS",
    "OrderError",
    "OrderNotFoundError",
    "apply_payment_result",
    "assert_order_transition",
    "can_transition_order",
    "cart_from_json",
    "create_order_from_cart",
    "create_pix_for_order",
    "format_order_code",
    "get_order_summary",
    "get_pending_payment",
    "list_orders",
    "notify_agent_payment_approved",
    "update_order_status",
]
