"""Monitoramento das conversas do agente.

Leitura pura das tabelas do agente, mais o botão de handoff — que é como o
lojista assume a conversa e cala o bot.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, not_found
from app.schemas.conversation import (
    ConversationMessageRead,
    ConversationRead,
    HandoffResult,
    HandoffUpdate,
)
from app.services import conversations as conversations_service

router = APIRouter(prefix="/api/conversations", tags=["conversas"])


@router.get("", response_model=list[ConversationRead])
async def list_conversations(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ConversationRead]:
    return await conversations_service.list_conversations(
        session, limit=limit, offset=offset
    )


@router.get("/{conversation_id}/messages", response_model=list[ConversationMessageRead])
async def list_messages(
    conversation_id: UUID,
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ConversationMessageRead]:
    conversation = await conversations_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise not_found("Conversa não encontrada.")
    return await conversations_service.list_messages(
        session, conversation_id, limit=limit
    )


@router.post("/{conversation_id}/handoff", response_model=HandoffResult)
async def toggle_handoff(
    conversation_id: UUID, payload: HandoffUpdate, session: SessionDep
) -> HandoffResult:
    """Com `handoff=true` o agente para de responder este telefone."""
    conversation = await conversations_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise not_found("Conversa não encontrada.")
    await conversations_service.set_handoff(
        session, conversation, handoff=payload.handoff
    )
    await session.commit()
    return HandoffResult(
        id=conversation.id, handoff=conversation.handoff, state=conversation.state
    )
