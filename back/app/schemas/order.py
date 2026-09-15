"""DTOs de pedido.

`OrderCreated` e `OrderSummary` são contrato com o agente de WhatsApp
(Agente 2); os demais servem ao Kanban do painel.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import FulfillmentType, OrderChannel, OrderStatus, PaymentStatus
from app.schemas.common import Money, ORMModel

# ---------------------------------------------------------------------------
# Contrato com o agente
# ---------------------------------------------------------------------------


class OrderCreated(BaseModel):
    """Retorno de `create_order_from_cart` — o mínimo para o agente responder."""

    id: UUID
    code: str
    subtotal: Money
    delivery_fee: Money
    total: Money
    status: OrderStatus = OrderStatus.NOVO
    payment_status: PaymentStatus = PaymentStatus.PENDENTE


class OrderSummaryItem(BaseModel):
    product_name: str
    quantity: int
    complements: list[str] = Field(default_factory=list)
    unit_price: Money
    line_total: Money
    details: str | None = None


class OrderSummary(BaseModel):
    """Resumo legível de um pedido, usado pelo agente ao responder o cliente."""

    id: UUID
    code: str
    status: OrderStatus
    payment_status: PaymentStatus
    fulfillment_type: FulfillmentType
    subtotal: Money
    delivery_fee: Money
    total: Money
    items: list[OrderSummaryItem] = Field(default_factory=list)
    customer_name: str | None = None
    customer_phone: str | None = None
    address_line: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    paid_at: datetime | None = None
    pix_qr_code: str | None = None  # copia-e-cola da última cobrança pendente


# ---------------------------------------------------------------------------
# Leitura (painel / Kanban)
# ---------------------------------------------------------------------------


class OrderItemComplementRead(ORMModel):
    id: UUID
    complement_id: UUID | None = None
    complement_name_snapshot: str
    extra_price_snapshot: Money


class OrderItemRead(ORMModel):
    id: UUID
    product_id: UUID | None = None
    product_name_snapshot: str
    unit_base_price: Money
    quantity: int
    line_total: Money
    details: str | None = None
    complements: list[OrderItemComplementRead] = Field(default_factory=list)


class PaymentRead(ORMModel):
    id: UUID
    provider: str
    provider_payment_id: str | None = None
    method: str
    amount: Money
    status: PaymentStatus
    qr_code: str | None = None
    ticket_url: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


class AddressRead(ORMModel):
    id: UUID
    rua: str
    numero: str
    bairro: str
    complemento: str | None = None
    referencia: str | None = None


class CustomerRead(ORMModel):
    id: UUID
    phone: str
    name: str | None = None


class OrderRead(ORMModel):
    id: UUID
    code: str
    status: OrderStatus
    payment_status: PaymentStatus
    fulfillment_type: FulfillmentType
    channel: OrderChannel
    subtotal: Money
    delivery_fee: Money
    total: Money
    notes: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    paid_at: datetime | None = None
    cancelled_at: datetime | None = None
    customer: CustomerRead | None = None
    address: AddressRead | None = None
    items: list[OrderItemRead] = Field(default_factory=list)
    payments: list[PaymentRead] = Field(default_factory=list)


class OrderStatusUpdate(BaseModel):
    """Corpo de `PATCH /api/orders/{id}/status`."""

    status: OrderStatus

    ticket_url: str | None = None
    expires_at: datetime | None = None


__all__ = [
    "AddressRead",
    "CustomerRead",
    "OrderCreated",
    "OrderItemComplementRead",
    "OrderItemRead",
    "OrderRead",
    "OrderStatusUpdate",
    "OrderSummary",
    "OrderSummaryItem",
    "PaymentRead",
]
