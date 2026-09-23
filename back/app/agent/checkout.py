"""Fechamento do pedido — a parte do agente que tem efeito colateral.

O executor (`machine.py`) decide o que acontece; este módulo é o que de fato
cria o pedido no banco e pede o Pix ao provedor. Ficam juntos aqui porque é a
resposta para "onde o pedido nasce": endereço, resumo final, criação do pedido,
cobrança e consulta de status.

As dependências externas chegam por `AgentDeps`, injetadas em `build_deps()`.
É isso que permite testar o fluxo inteiro sem banco e sem Mercado Pago.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.agent import renderer as r
from app.agent.session import ConversationSession
from app.agent.states import advance
from app.core.config import Settings, get_settings
from app.domain.catalog import CatalogSnapshot
from app.domain.enums import ConversationState as S
from app.domain.enums import FulfillmentType, OrderChannel

logger = logging.getLogger(__name__)

CreateOrder = Callable[..., Awaitable[Any]]
CreatePix = Callable[..., Awaitable[Any]]
OrderSummaryFn = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class AgentDeps:
    """Tudo que o agente consome de fora — injetado para poder testar sem banco."""

    db: Any
    catalog: CatalogSnapshot
    settings: Settings
    create_order: CreateOrder
    create_pix: CreatePix
    order_summary: OrderSummaryFn
    saved_address: Callable[[], Awaitable[dict[str, Any] | None]] | None = None
    channel: OrderChannel = OrderChannel.WHATSAPP


async def build_deps(
    db: Any,
    catalog: CatalogSnapshot,
    *,
    phone: str | None = None,
    channel: OrderChannel = OrderChannel.WHATSAPP,
) -> AgentDeps:
    """Monta as dependências reais. Import tardio evita ciclo com os serviços."""
    from app.services.orders import (  # noqa: PLC0415  (import tardio proposital)
        create_order_from_cart,
        get_order_summary,
    )
    from app.services.payments import create_pix_for_order  # noqa: PLC0415

    async def _saved_address() -> dict[str, Any] | None:
        if phone is None:
            return None
        from app.agent.session import get_saved_address  # noqa: PLC0415

        return await get_saved_address(db, phone)

    return AgentDeps(
        db=db,
        catalog=catalog,
        settings=get_settings(),
        create_order=create_order_from_cart,
        create_pix=create_pix_for_order,
        order_summary=get_order_summary,
        saved_address=_saved_address,
        channel=channel,
    )


# ---------------------------------------------------------------------------
# Endereço
# ---------------------------------------------------------------------------

def address_of(session: ConversationSession) -> dict[str, Any]:
    address = session.slots.get("address")
    return dict(address) if isinstance(address, dict) else {}


def missing_address_fields(address: dict[str, Any]) -> list[str]:
    return [f for f in ("rua", "numero", "bairro") if not (address.get(f) or "").strip()]


#: Slot onde fica a escolha do cliente: "entrega" ou "retirada".
FULFILLMENT_SLOT = "fulfillment"


def fulfillment_of(session: ConversationSession) -> FulfillmentType | None:
    """O que o cliente escolheu, ou None se ainda não foi perguntado."""
    raw = session.slots.get(FULFILLMENT_SLOT)
    if raw in (FulfillmentType.RETIRADA, FulfillmentType.RETIRADA.value):
        return FulfillmentType.RETIRADA
    if raw in (FulfillmentType.ENTREGA, FulfillmentType.ENTREGA.value):
        return FulfillmentType.ENTREGA
    return None


def set_fulfillment(session: ConversationSession, kind: FulfillmentType) -> None:
    session.slots[FULFILLMENT_SLOT] = kind.value


def final_summary(deps: AgentDeps, session: ConversationSession) -> str:
    return r.final_summary(
        session.cart,
        delivery_fee=deps.settings.delivery_fee,
        address=address_of(session),
        is_pickup=fulfillment_of(session) is FulfillmentType.RETIRADA,
    )


# ---------------------------------------------------------------------------
# Do carrinho ao Pix
# ---------------------------------------------------------------------------

async def place_order(deps: AgentDeps, session: ConversationSession) -> list[str]:
    """Cria o pedido, gera o Pix e leva para AGUARDANDO_PAGAMENTO.

    Guarda o id do pedido em `pending_order_id` assim que ele é criado: se o
    Pix falhar depois (provedor fora do ar, token ausente) e o cliente mandar
    "sim" de novo, reaproveitamos o mesmo pedido em vez de duplicar a compra.
    """
    pending_id = session.slots.get("pending_order_id")
    kind = fulfillment_of(session) or FulfillmentType.ENTREGA
    try:
        if pending_id:
            summary = await deps.order_summary(deps.db, UUID(pending_id))
        else:
            summary = None

        if summary is not None:
            order_id, order_code, order_total = UUID(pending_id), summary.code, summary.total
        else:
            order = await deps.create_order(
                deps.db,
                cart=session.cart,
                phone=session.phone,
                customer_name=session.slots.get("customer_name"),
                fulfillment_type=kind,
                # Retirada não tem endereço: mandar um dict vazio criaria uma
                # linha em `addresses` sem rua nem número.
                address=address_of(session) if kind is FulfillmentType.ENTREGA else None,
                channel=deps.channel,
                notes=session.slots.get("notes"),
            )
            order_id, order_code, order_total = order.id, order.code, order.total
            session.slots["pending_order_id"] = str(order_id)

        charge = await deps.create_pix(deps.db, order_id)
    except Exception:
        logger.exception("falha ao criar pedido/Pix para %s", session.phone)
        return [r.pix_failed()]

    session.active_order_id = order_id
    session.cart.items.clear()
    session.slots.pop("pending_order_id", None)
    # "draft" é de conversas abertas na versão anterior do executor; some junto
    # para a próxima conversa desse cliente começar limpa.
    session.slots.pop("draft", None)
    session.slots.pop("closing", None)
    session.slots.pop("awaiting_confirm", None)
    session.fail_count = 0
    advance(session, S.AGUARDANDO_PAGAMENTO)
    return [
        r.pix_message(
            order_code=order_code,
            total=order_total,
            qr_code=charge.qr_code,
            expires_minutes=deps.settings.pix_expiration_minutes,
        )
    ]


async def order_status_reply(deps: AgentDeps, session: ConversationSession) -> list[str]:
    """Situação do pedido ativo — o cliente pode perguntar em qualquer estado."""
    if session.active_order_id is None:
        return [r.no_active_order()]
    try:
        summary = await deps.order_summary(deps.db, session.active_order_id)
    except Exception:
        logger.exception("falha ao consultar pedido %s", session.active_order_id)
        summary = None
    if summary is None:
        return [r.no_active_order()]
    return [r.order_status(summary)]
