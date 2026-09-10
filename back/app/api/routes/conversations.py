"""Monitoramento das conversas do agente.

Leitura pura das tabelas do agente, mais o botão de handoff — que é como o
lojista assume a conversa e cala o bot.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, not_found
from app.repositories import conversations as conversations_repo
from app.repositories import customers as customers_repo
from app.schemas.conversation import (
    ConversationMessageRead,
    ConversationRead,
    HandoffResult,
    HandoffUpdate,
)

router = APIRouter(prefix="/api/conversations", tags=["conversas"])


#: Corta a prévia pra caber numa linha da lista (o histórico completo tem o texto inteiro).
_PREVIEW_MAX_LEN = 80


def _preview(content: str | None) -> str | None:
    if not content:
        return None
    flat = " ".join(content.split())
    return flat if len(flat) <= _PREVIEW_MAX_LEN else flat[: _PREVIEW_MAX_LEN - 1] + "…"


async def _to_read(
    session: SessionDep, conversation, last_message: str | None
) -> ConversationRead:  # type: ignore[no-untyped-def]
    """Anexa o nome do cliente (mora em `customers`, não na conversa) e a prévia."""
    data = ConversationRead.model_validate(conversation)
    data = data.model_copy(update={"last_message_preview": _preview(last_message)})
    if conversation.customer_id:
        customer = await customers_repo.get_customer(session, conversation.customer_id)
        if customer is not None:
            data = data.model_copy(update={"customer_name": customer.name})
    return data


@router.get("", response_model=list[ConversationRead])
async def list_conversations(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ConversationRead]:
    rows = await conversations_repo.list_conversations(session, limit=limit, offset=offset)
    return [await _to_read(session, conversation, last_message) for conversation, last_message in rows]


@router.get("/{conversation_id}/messages", response_model=list[ConversationMessageRead])
async def list_messages(
    conversation_id: UUID,
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ConversationMessageRead]:
    conversation = await conversations_repo.get_conversation(session, conversation_id)
    if conversation is None:
        raise not_found("Conversa não encontrada.")
    messages = await conversations_repo.list_messages(
        session, conversation_id, limit=limit
    )
    return [ConversationMessageRead.model_validate(m) for m in messages]


@router.post("/{conversation_id}/handoff", response_model=HandoffResult)
async def toggle_handoff(
    conversation_id: UUID, payload: HandoffUpdate, session: SessionDep
) -> HandoffResult:
    """Com `handoff=true` o runner do agente para de responder este telefone."""
    conversation = await conversations_repo.get_conversation(session, conversation_id)
    if conversation is None:
        raise not_found("Conversa não encontrada.")
    await conversations_repo.set_handoff(session, conversation, handoff=payload.handoff)
    await session.commit()
    return HandoffResult(
        id=conversation.id, handoff=conversation.handoff, state=conversation.state
    )
