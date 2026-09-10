"""Leitura das tabelas do agente para a tela de monitoramento.

Quem escreve em `conversations`/`conversation_messages` é o agente (Agente 2);
o painel só lê — a única exceção é o toggle de handoff.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ConversationMessage


async def list_conversations(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[tuple[Conversation, str | None]]:
    """Cada linha vem com o texto da última mensagem, pra lista parecer WhatsApp."""
    last_message = (
        select(ConversationMessage.content)
        .where(ConversationMessage.conversation_id == Conversation.id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    result = await session.execute(
        select(Conversation, last_message)
        .order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_conversation(
    session: AsyncSession, conversation_id: UUID
) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


async def list_messages(
    session: AsyncSession, conversation_id: UUID, *, limit: int = 200
) -> list[ConversationMessage]:
    result = await session.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at)
        .limit(limit)
    )
    return list(result)


async def set_handoff(
    session: AsyncSession, conversation: Conversation, *, handoff: bool
) -> Conversation:
    conversation.handoff = handoff
    await session.flush()
    return conversation


__all__ = [
    "get_conversation",
    "list_conversations",
    "list_messages",
    "set_handoff",
]
