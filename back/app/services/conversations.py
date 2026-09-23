"""Leitura das conversas do agente e o botão de "assumir o atendimento".

Quem escreve em `conversations`/`conversation_messages` é o agente; o painel só
lê. A única escrita daqui é o toggle de handoff, que é como o lojista cala o bot
para responder ele mesmo.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ConversationMessage, Customer
from app.domain.enums import ConversationState
from app.schemas.conversation import ConversationMessageRead, ConversationRead

#: Corta a prévia pra caber numa linha da lista (o histórico tem o texto inteiro).
_PREVIEW_MAX_LEN = 80


def _preview(content: str | None) -> str | None:
    if not content:
        return None
    flat = " ".join(content.split())
    return flat if len(flat) <= _PREVIEW_MAX_LEN else flat[: _PREVIEW_MAX_LEN - 1] + "…"


async def list_conversations(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[ConversationRead]:
    """Lista para o painel, cada linha já com nome do cliente e prévia.

    O nome mora em `customers`, não na conversa; os clientes das conversas
    listadas são carregados de uma vez só para não fazer uma consulta por linha.
    """
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
    rows = [(row[0], row[1]) for row in result.all()]

    customer_ids = {c.customer_id for c, _ in rows if c.customer_id}
    names: dict[UUID, str | None] = {}
    if customer_ids:
        customers = await session.scalars(
            select(Customer).where(Customer.id.in_(customer_ids))
        )
        names = {c.id: c.name for c in customers}

    return [
        ConversationRead.model_validate(conversation).model_copy(
            update={
                "last_message_preview": _preview(last_message_text),
                "customer_name": names.get(conversation.customer_id),
            }
        )
        for conversation, last_message_text in rows
    ]


async def get_conversation(
    session: AsyncSession, conversation_id: UUID
) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


async def list_messages(
    session: AsyncSession, conversation_id: UUID, *, limit: int = 200
) -> list[ConversationMessageRead]:
    """Histórico completo da conversa, do mais antigo para o mais novo."""
    result = await session.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at)
        .limit(limit)
    )
    return [ConversationMessageRead.model_validate(m) for m in result]


async def set_handoff(
    session: AsyncSession, conversation: Conversation, *, handoff: bool
) -> Conversation:
    """`handoff=True` faz o agente parar de responder este telefone.

    Devolver a conversa para o bot (`handoff=False`) precisa também tirá-la do
    estado ATENDIMENTO_HUMANO: a máquina de estados fica calada com base no
    ESTADO (`machine.run`), não neste booleano. Sem isso, uma conversa que o
    próprio bot escalou — o que acontece depois de MAX_NLU_FAILURES falhas —
    ficaria muda para sempre, mesmo o lojista clicando em "devolver ao bot".

    O carrinho é preservado de propósito: o cliente pode ter montado o pedido
    antes da escalada e não deve perdê-lo. Só o contador de falhas é zerado,
    senão a próxima incompreensão escalaria a conversa na hora de novo.
    """
    conversation.handoff = handoff

    if not handoff and conversation.state == ConversationState.ATENDIMENTO_HUMANO:
        conversation.state = ConversationState.CONVERSANDO
        conversation.fail_count = 0

    await session.flush()
    return conversation
