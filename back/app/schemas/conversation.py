"""DTOs da tela de monitoramento do agente.

O painel só lê estas tabelas (quem escreve nelas é o Agente 2); a única escrita
exposta é o toggle de handoff, que pausa o bot para um humano assumir.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import MessageDirection
from app.schemas.common import ORMModel


class ConversationRead(ORMModel):
    id: UUID
    phone: str
    channel: str
    state: str
    handoff: bool
    fail_count: int
    customer_name: str | None = None
    last_message_preview: str | None = None
    active_order_id: UUID | None = None
    last_message_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationMessageRead(ORMModel):
    id: UUID
    direction: MessageDirection
    content: str
    state_before: str | None = None
    state_after: str | None = None
    detected_intent: str | None = None
    confidence: Decimal | None = None
    llm_model: str | None = None
    created_at: datetime


class HandoffUpdate(BaseModel):
    """Corpo de `POST /api/conversations/{id}/handoff`."""

    handoff: bool


class HandoffResult(BaseModel):
    id: UUID
    handoff: bool
    state: str


class ConversationList(BaseModel):
    conversations: list[ConversationRead] = Field(default_factory=list)


__all__ = [
    "ConversationList",
    "ConversationMessageRead",
    "ConversationRead",
    "HandoffResult",
    "HandoffUpdate",
]
