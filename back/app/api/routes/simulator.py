"""Simulador de conversa — testar o agente inteiro sem WhatsApp.

Só existe com `FAKE_MODE=true`. Em produção qualquer chamada aqui devolve 404:
seria um jeito trivial de escrever no estado de conversas reais sem passar por
autenticação nenhuma.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.channels.base import InboundMessage
from app.agent.runner import handle_inbound
from app.agent.session import load_or_create, reset_session
from app.core.config import get_settings
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulator", tags=["simulador"])

CHANNEL = "simulador"


class SimulatorMessage(BaseModel):
    phone: str = Field(min_length=3, max_length=32)
    text: str = Field(min_length=1, max_length=2000)


class SimulatorReply(BaseModel):
    replies: list[str]
    state: str


class SimulatorReset(BaseModel):
    phone: str = Field(min_length=3, max_length=32)


def _guard() -> None:
    """O simulador é ferramenta de desenvolvimento; não vaza para produção."""
    if not get_settings().fake_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulador disponível apenas com FAKE_MODE=true",
        )


@router.post("/message", response_model=SimulatorReply)
async def send_message(
    payload: SimulatorMessage,
    db: AsyncSession = Depends(get_session),
) -> SimulatorReply:
    """Manda uma mensagem como se fosse o cliente e devolve o que o bot diria."""
    _guard()

    message = InboundMessage(phone=payload.phone, text=payload.text)
    replies = await handle_inbound(db, message, channel_name=CHANNEL)
    conversation = await load_or_create(db, payload.phone, CHANNEL)
    await db.commit()

    return SimulatorReply(replies=replies, state=conversation.state.value)


@router.post("/reset", response_model=SimulatorReply)
async def reset(
    payload: SimulatorReset,
    db: AsyncSession = Depends(get_session),
) -> SimulatorReply:
    """Volta a conversa para o início e apaga o histórico de mensagens."""
    _guard()

    conversation = await reset_session(db, payload.phone, CHANNEL)
    await db.commit()
    return SimulatorReply(replies=[], state=conversation.state.value)
