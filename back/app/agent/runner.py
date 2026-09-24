"""Orquestração de um turno de conversa.

Junta as peças na ordem certa: sessão → LLM → máquina de estados →
persistência → canal. É o único ponto que o mundo externo (webhook do
WhatsApp, simulador, CLI) precisa chamar.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.agent import renderer as r
from app.agent.checkout import AgentDeps, build_deps
from app.agent.llm import get_llm_client
from app.agent.machine import describe_situation
from app.agent.machine import run as run_machine
from app.agent.plan import AgentPlan
from app.agent.session import (
    ConversationSession,
    already_seen,
    find_by_active_order,
    load_or_create,
    log_message,
    recent_turns,
    save_session,
)
from app.agent.states import assert_transition
from app.agent.whatsapp import InboundMessage, get_channel_adapter
from app.core.config import get_settings
from app.domain.catalog import CatalogSnapshot
from app.domain.enums import ConversationState, MessageDirection, OrderChannel

logger = logging.getLogger(__name__)

_CHANNEL_TO_ORDER_CHANNEL = {
    "whatsapp": OrderChannel.WHATSAPP,
    "console": OrderChannel.SIMULADOR,
    "simulador": OrderChannel.SIMULADOR,
}


# Indireções nomeadas: os testes trocam estas funções por fakes, e o import
# tardio evita ciclo com os serviços do catálogo/pedidos.
async def _fetch_catalog(db: Any) -> CatalogSnapshot:
    from app.services.catalog import get_catalog_snapshot  # noqa: PLC0415

    return await get_catalog_snapshot(db)


async def _build_deps(db: Any, catalog: CatalogSnapshot, session: ConversationSession) -> AgentDeps:
    return await build_deps(
        db,
        catalog,
        phone=session.phone,
        channel=_CHANNEL_TO_ORDER_CHANNEL.get(session.channel, OrderChannel.WHATSAPP),
    )


async def handle_inbound(
    session: Any,
    message: InboundMessage,
    *,
    channel_name: str = "whatsapp",
) -> list[str]:
    """Processa uma mensagem recebida e devolve o que o agente respondeu.

    `session` aqui é a sessão do BANCO (AsyncSession) — o estado da conversa
    é carregado dentro. Em atendimento humano o executor decide o que fazer:
    ele para de conduzir o pedido, mas continua ouvindo (ver `machine`).
    """
    if await already_seen(session, message.provider_message_id):
        logger.info(
            "mensagem %s reentregue pelo canal; já foi atendida",
            message.provider_message_id,
        )
        return []

    conversation = await load_or_create(session, message.phone, channel_name)
    state_before = conversation.state

    if message.profile_name and "customer_name" not in conversation.slots:
        conversation.slots["customer_name"] = message.profile_name

    catalog = await _fetch_catalog(session)
    deps = await _build_deps(session, catalog, conversation)
    situation = describe_situation(deps, conversation)
    plan = await _interpret(session, conversation, catalog, message.text, situation)
    replies = await run_machine(deps, conversation, plan, message.text)

    await save_session(session, conversation)
    await log_message(
        session,
        conversation_id=conversation.id,
        direction=MessageDirection.ENTRADA,
        content=message.text,
        state_before=state_before,
        state_after=conversation.state,
        detected_intent=_first_action(plan),
        confidence=plan.confidence,
        llm_model=plan.model,
        llm_usage=plan.usage,
        provider_message_id=message.provider_message_id,
    )

    await _deliver(session, conversation, replies, channel_name)
    return replies


async def handle_outbound_echo(
    session: Any, message: InboundMessage, *, channel_name: str = "whatsapp"
) -> None:
    """Registra uma mensagem que SAIU do número da loja sem passar pelo bot.

    Cobre duas origens, ambas com `key.fromMe=true` no Baileys: o eco do que o
    próprio bot mandou (já registrado em `_deliver`, então aqui só bate no
    `ON CONFLICT` e não duplica) e uma resposta que o lojista digitou na mão no
    celular — essa é nova, e é o que faz o painel espelhar a conversa inteira,
    não só o que o bot conduziu. Nunca chama o LLM nem a máquina de estados.
    """
    conversation = await load_or_create(session, message.phone, channel_name)
    await log_message(
        session,
        conversation_id=conversation.id,
        direction=MessageDirection.SAIDA,
        content=message.text,
        state_after=conversation.state,
        provider_message_id=message.provider_message_id,
    )

    if conversation.handoff:
        # Alguém da loja está respondendo pelo celular: o relógio que devolve a
        # conversa ao bot recomeça a cada fala humana. (Em handoff o bot não
        # envia nada, então todo `fromMe` daqui é gente de verdade.)
        conversation.touch_handoff()
        await save_session(session, conversation)


async def _interpret(
    db: Any,
    conversation: ConversationSession,
    catalog: CatalogSnapshot,
    text: str,
    situation: str,
) -> AgentPlan:
    """Chama o LLM; qualquer falha vira plano vazio e o executor repergunta."""
    try:
        history = await recent_turns(db, conversation.id)
    except Exception:
        logger.warning("sem histórico para o LLM", exc_info=True)
        history = []

    try:
        return await get_llm_client().interpret(
            catalog=catalog,
            history=history,
            message=text,
            situation=situation,
        )
    except Exception:
        # O cliente real já trata os próprios erros; isto é o cinto de segurança.
        logger.exception("cliente de LLM levantou exceção inesperada")
        return AgentPlan()


def _first_action(plan: AgentPlan) -> str | None:
    """O que vai para o painel na coluna de intenção."""
    return plan.operations[0].action.value if plan.operations else None


async def _deliver(
    db: Any,
    conversation: ConversationSession,
    replies: list[str],
    channel_name: str,
) -> None:
    """Envia pelo canal e registra cada resposta em conversation_messages."""
    adapter = get_channel_adapter(channel_name)
    for reply in replies:
        provider_id = None
        try:
            provider_id = await adapter.send_text(conversation.phone, reply)
        except Exception:
            logger.exception("falha ao enviar resposta por %s", channel_name)
        await log_message(
            db,
            conversation_id=conversation.id,
            direction=MessageDirection.SAIDA,
            content=reply,
            state_after=conversation.state,
            provider_message_id=provider_id,
        )


async def notify_payment_approved(session: Any, order_id: UUID) -> None:
    """Avisa o cliente que o Pix caiu e fecha a conversa.

    Chamada pelo webhook do Mercado Pago. Nunca levanta: um erro aqui não pode
    fazer o provedor reenviar a notificação para sempre.
    """
    try:
        conversation = await find_by_active_order(session, order_id)
    except Exception:
        logger.exception("falha ao localizar conversa do pedido %s", order_id)
        return

    if conversation is None:
        logger.info("pagamento aprovado sem conversa associada (pedido %s)", order_id)
        return

    code = await _order_code(session, order_id)
    text = r.payment_confirmed(code)

    if conversation.state is ConversationState.AGUARDANDO_PAGAMENTO:
        assert_transition(conversation.state, ConversationState.CONCLUIDO)
        conversation.state = ConversationState.CONCLUIDO
    else:
        logger.info(
            "pagamento aprovado com a conversa em %s; só avisando o cliente",
            conversation.state,
        )

    conversation.slots.pop("options", None)
    conversation.fail_count = 0

    try:
        await save_session(session, conversation)
    except Exception:
        logger.exception("falha ao salvar conversa após pagamento")

    if conversation.handoff:
        return  # atendente humano na linha: ele avisa

    await _deliver(session, conversation, [text], conversation.channel)


async def _order_code(db: Any, order_id: UUID) -> str:
    """Código curto do pedido para a mensagem; cai no id se o serviço falhar."""
    try:
        from app.services.orders import get_order_summary  # noqa: PLC0415

        summary = await get_order_summary(db, order_id)
    except Exception:
        logger.warning("não foi possível ler o pedido %s", order_id, exc_info=True)
        summary = None
    return getattr(summary, "code", None) or str(order_id)[:8]


def settings_snapshot() -> dict[str, Any]:
    """Pequeno diagnóstico usado pela CLI e pelo simulador."""
    settings = get_settings()
    return {
        "fake_mode": settings.fake_mode,
        "llm": get_llm_client().name,
        "model": settings.openai_model,
    }
