"""Regras de pedido: fechamento do carrinho e mudança de status.

Este módulo é a fronteira entre a conversa (carrinho em JSON) e o pedido real:
é aqui que o preço é congelado, o código curto é emitido e o cliente vira uma
entidade do banco. Nada disso pode depender do que o LLM devolveu.

O ciclo do pagamento (criar o Pix, aplicar o resultado) mora em
`services/payments.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Order, OrderItem, OrderItemComplement, order_code_seq
from app.domain.cart import Cart, item_unit_price, money
from app.domain.enums import FulfillmentType, OrderChannel, OrderStatus, PaymentStatus
from app.schemas.order import OrderCreated, OrderSummary, OrderSummaryItem
from app.services import customers as customers_service
from app.services import pricing

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Acesso a dados
# ---------------------------------------------------------------------------


async def list_orders(
    session: AsyncSession,
    *,
    status: OrderStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Order]:
    """Lista para o Kanban: mais recentes primeiro, com itens e pagamentos."""
    stmt = select(Order).order_by(Order.created_at.desc()).limit(limit).offset(offset)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    result = await session.scalars(stmt)
    return list(result)


async def get_order(session: AsyncSession, order_id: UUID) -> Order | None:
    return await session.get(Order, order_id)


async def next_code_number(session: AsyncSession) -> int:
    """`nextval('order_code_seq')` — números sem colisão mesmo em concorrência."""
    value = await session.scalar(select(order_code_seq.next_value()))
    return int(value)


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
    code = format_order_code(await next_code_number(session))

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
            unit_base_price=money(cart_item.unit_base_price),
            quantity=cart_item.quantity,
            line_total=cart_item.line_total,
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
                    extra_price_snapshot=money(complement.extra_price),
                )
            )

    await session.flush()
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
# Status e leitura
# ---------------------------------------------------------------------------


async def update_order_status(
    session: AsyncSession, order_id: UUID, new_status: OrderStatus
) -> Order:
    order = await get_order(session, order_id)
    if order is None:
        raise OrderNotFoundError(f"Pedido {order_id} não encontrado.")

    assert_order_transition(order.status, new_status)
    if order.status == new_status:
        return order

    order.status = new_status
    if new_status is OrderStatus.CANCELADO:
        order.cancelled_at = datetime.now(timezone.utc)
    await session.flush()
    logger.info("Pedido %s -> %s", order.code, new_status)
    return order


def _summary_item(item: OrderItem) -> OrderSummaryItem:
    unit_price = item_unit_price(
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
    order = await get_order(session, order_id)
    if order is None:
        return None

    # Import tardio: services.payments importa daqui (OrderError, get_order).
    from app.services.payments import get_pending_payment  # noqa: PLC0415

    pending = await get_pending_payment(session, order.id)
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



__all__ = [
    "EmptyCartError",
    "InvalidStatusTransition",
    "MissingAddressError",
    "ORDER_TRANSITIONS",
    "OrderError",
    "OrderNotFoundError",
    "assert_order_transition",
    "can_transition_order",
    "create_order_from_cart",
    "format_order_code",
    "get_order_summary",
    "list_orders",
    "update_order_status",
]
