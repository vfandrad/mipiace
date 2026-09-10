"""Pedidos para o painel: Kanban, detalhe e mudança de status."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, conflict, not_found
from app.domain.enums import OrderStatus
from app.repositories import orders as orders_repo
from app.schemas.order import OrderRead, OrderStatusUpdate, OrderSummary
from app.services import orders as orders_service

router = APIRouter(prefix="/api", tags=["pedidos"])


@router.get("/orders", response_model=list[OrderRead])
async def list_orders(
    session: SessionDep,
    status: OrderStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[OrderRead]:
    """Lista para o Kanban, já com itens, complementos e pagamentos."""
    orders = await orders_service.list_orders(
        session, status=status, limit=limit, offset=offset
    )
    return [OrderRead.model_validate(order) for order in orders]


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(order_id: UUID, session: SessionDep) -> OrderRead:
    order = await orders_repo.get_order(session, order_id)
    if order is None:
        raise not_found("Pedido não encontrado.")
    return OrderRead.model_validate(order)


@router.get("/orders/{order_id}/summary", response_model=OrderSummary)
async def get_order_summary(order_id: UUID, session: SessionDep) -> OrderSummary:
    """Mesmo resumo que o agente usa para falar com o cliente."""
    summary = await orders_service.get_order_summary(session, order_id)
    if summary is None:
        raise not_found("Pedido não encontrado.")
    return summary


@router.patch("/orders/{order_id}/status", response_model=OrderRead)
async def update_status(
    order_id: UUID, payload: OrderStatusUpdate, session: SessionDep
) -> OrderRead:
    """Move o pedido no Kanban validando a transição (409 se for salto inválido)."""
    try:
        order = await orders_service.update_order_status(
            session, order_id, payload.status
        )
    except orders_service.OrderNotFoundError as exc:
        raise not_found(str(exc)) from exc
    except orders_service.InvalidStatusTransition as exc:
        raise conflict(str(exc)) from exc
    return OrderRead.model_validate(order)
