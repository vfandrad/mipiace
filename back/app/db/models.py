"""Modelos SQLAlchemy 2.0 que espelham `back/db/schema.sql`.

O schema.sql continua sendo a fonte de verdade (é ele que roda no Postgres via
docker-entrypoint-initdb.d). Estes modelos existem para dar acesso tipado ao
mesmo desenho — por isso nada de `metadata.create_all()`: os tipos ENUM nativos,
as sequences e as views são criados pelo SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    Sequence,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.enums import (
    FulfillmentType,
    MessageDirection,
    OrderChannel,
    OrderStatus,
    PaymentStatus,
)


class Base(DeclarativeBase):
    """Base declarativa única do projeto."""


# --- Fábricas de coluna reaproveitadas ---------------------------------------
# São 13 tabelas com o mesmo trio id/created_at/dinheiro; centralizar evita que
# uma delas nasça com float ou sem timezone.


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PGUuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


def _timestamp() -> Mapped[datetime]:
    return mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


def _money(default: str | None = None) -> Mapped[Decimal]:
    return mapped_column(
        Numeric(10, 2),
        nullable=False,
        server_default=default,
        default=Decimal(default) if default is not None else None,
    )


def _pg_enum(python_enum: type, name: str) -> PGEnum:
    """ENUM nativo do Postgres já criado por schema.sql (create_type=False)."""
    return PGEnum(
        python_enum,
        name=name,
        create_type=False,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


# ============================================================================
# CATÁLOGO
# ============================================================================


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    groups: Mapped[list[ComplementGroup]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ComplementGroup.sort_order, ComplementGroup.name",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("base_price >= 0", name="products_base_price_check"),
    )


class FlavorCategory(Base):
    """Atributo do sabor em si ("Sem lactose" / "Com lactose"), não do grupo."""

    __tablename__ = "flavor_categories"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()


class ComplementGroup(Base):
    __tablename__ = "complement_groups"

    id: Mapped[uuid.UUID] = _pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUuid(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    min_choices: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_choices: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    product: Mapped[Product] = relationship(back_populates="groups")
    complements: Mapped[list[Complement]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="Complement.sort_order, Complement.name",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("max_choices >= min_choices", name="chk_choices_range"),
    )


class Complement(Base):
    __tablename__ = "complements"

    id: Mapped[uuid.UUID] = _pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUuid(as_uuid=True),
        ForeignKey("complement_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    extra_price: Mapped[Decimal] = _money("0")
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # NULL para complementos que não são sabores (cobertura, adicional, calda).
    flavor_category_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUuid(as_uuid=True),
        ForeignKey("flavor_categories.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    group: Mapped[ComplementGroup] = relationship(back_populates="complements")
    flavor_category: Mapped[FlavorCategory | None] = relationship(lazy="selectin")


# ============================================================================
# CLIENTES
# ============================================================================


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = _pk()
    phone: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    addresses: Mapped[list[Address]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="Address.created_at.desc()",
        lazy="selectin",
    )


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[uuid.UUID] = _pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PGUuid(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    rua: Mapped[str] = mapped_column(Text, nullable=False)
    numero: Mapped[str] = mapped_column(Text, nullable=False)
    bairro: Mapped[str] = mapped_column(Text, nullable=False)
    complemento: Mapped[str | None] = mapped_column(Text)
    referencia: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = _timestamp()

    customer: Mapped[Customer] = relationship(back_populates="addresses")


# ============================================================================
# PEDIDOS
# ============================================================================

#: Sequência do código curto do pedido (ver services/orders.py::next_order_code).
order_code_seq = Sequence("order_code_seq")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUuid(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    address_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUuid(as_uuid=True), ForeignKey("addresses.id", ondelete="SET NULL")
    )
    fulfillment_type: Mapped[FulfillmentType] = mapped_column(
        _pg_enum(FulfillmentType, "fulfillment_type"),
        nullable=False,
        default=FulfillmentType.ENTREGA,
    )
    channel: Mapped[OrderChannel] = mapped_column(
        _pg_enum(OrderChannel, "order_channel"),
        nullable=False,
        default=OrderChannel.WHATSAPP,
    )
    status: Mapped[OrderStatus] = mapped_column(
        _pg_enum(OrderStatus, "order_status"),
        nullable=False,
        default=OrderStatus.NOVO,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        _pg_enum(PaymentStatus, "payment_status"),
        nullable=False,
        default=PaymentStatus.PENDENTE,
    )
    subtotal: Mapped[Decimal] = _money("0")
    delivery_fee: Mapped[Decimal] = _money("0")
    total: Mapped[Decimal] = _money("0")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()
    paid_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    customer: Mapped[Customer | None] = relationship(lazy="selectin")
    address: Mapped[Address | None] = relationship(lazy="selectin")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.created_at",
        lazy="selectin",
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="Payment.created_at.desc()",
        lazy="selectin",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = _pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        PGUuid(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT")
    )
    # Snapshot: se o lojista mudar o preço amanhã, o histórico não pode mudar.
    product_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    unit_base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _timestamp()

    order: Mapped[Order] = relationship(back_populates="items")
    complements: Mapped[list[OrderItemComplement]] = relationship(
        back_populates="order_item",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrderItemComplement(Base):
    __tablename__ = "order_item_complements"

    id: Mapped[uuid.UUID] = _pk()
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUuid(as_uuid=True),
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    complement_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUuid(as_uuid=True), ForeignKey("complements.id", ondelete="RESTRICT")
    )
    complement_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    extra_price_snapshot: Mapped[Decimal] = _money("0")

    order_item: Mapped[OrderItem] = relationship(back_populates="complements")


# ============================================================================
# PAGAMENTOS
# ============================================================================


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = _pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        PGUuid(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(
        Text, nullable=False, default="pix", server_default="pix"
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        _pg_enum(PaymentStatus, "payment_status"),
        nullable=False,
        default=PaymentStatus.PENDENTE,
    )
    qr_code: Mapped[str | None] = mapped_column(Text)
    qr_code_base64: Mapped[str | None] = mapped_column(Text)
    ticket_url: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    order: Mapped[Order] = relationship(back_populates="payments")

    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_provider_payment"),
    )


class WebhookEvent(Base):
    """Idempotência de webhook: o Mercado Pago reenvia o mesmo evento."""

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = _pk()
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_webhook_event"),)


# ============================================================================
# AGENTE DE WHATSAPP
# ============================================================================


class Conversation(Base):
    """Memória da máquina de estados — uma linha por telefone/canal."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _pk()
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(
        Text, nullable=False, default="whatsapp", server_default="whatsapp"
    )
    state: Mapped[str] = mapped_column(
        Text, nullable=False, default="saudacao", server_default="saudacao"
    )
    slots: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    cart: Mapped[Any] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUuid(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    active_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUuid(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )
    handoff: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    fail_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )

    __table_args__ = (
        UniqueConstraint("phone", "channel", name="uq_conversation_phone_channel"),
    )


class ConversationMessage(Base):
    """Log de mensagens — auditoria do que a IA disse e quanto custou."""

    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = _pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction: Mapped[MessageDirection] = mapped_column(
        _pg_enum(MessageDirection, "message_direction"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    state_before: Mapped[str | None] = mapped_column(Text)
    state_after: Mapped[str | None] = mapped_column(Text)
    detected_intent: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    llm_model: Mapped[str | None] = mapped_column(Text)
    llm_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _timestamp()

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


__all__ = [
    "Address",
    "Base",
    "Complement",
    "ComplementGroup",
    "Conversation",
    "ConversationMessage",
    "Customer",
    "FlavorCategory",
    "Order",
    "OrderItem",
    "OrderItemComplement",
    "Payment",
    "Product",
    "WebhookEvent",
    "order_code_seq",
]
