"""Estado da conversa em `conversations` — a memória da máquina de estados.

Antes esse estado vivia dentro do n8n; agora vive no banco, o que permite
reiniciar o processo sem perder o pedido em construção e auditar o que a IA
disse (`conversation_messages`).

Aqui usamos SQL textual em vez dos modelos ORM de propósito: o esquema é o
contrato (`back/db/schema.sql`) e assim este módulo não fica acoplado às
classes SQLAlchemy de outra camada.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import text

from app.agent.llm import Turn
from app.core.config import get_settings
from app.domain.cart import Cart
from app.domain.enums import ConversationState, MessageDirection

logger = logging.getLogger(__name__)

DEFAULT_CHANNEL = "whatsapp"


@dataclass(slots=True)
class ConversationSession:
    """A linha de `conversations` já desserializada em objetos de domínio."""

    id: UUID
    phone: str
    channel: str
    state: ConversationState
    slots: dict[str, Any] = field(default_factory=dict)
    cart: Cart = field(default_factory=Cart)
    customer_id: UUID | None = None
    active_order_id: UUID | None = None
    handoff: bool = False
    fail_count: int = 0

    def reset_flow(self) -> None:
        """Zera o pedido em construção mantendo a identidade do cliente."""
        self.state = ConversationState.SAUDACAO
        self.slots = {}
        self.cart = Cart()
        self.active_order_id = None
        self.fail_count = 0

    def touch_handoff(self) -> None:
        """Marca agora como o último sinal de vida do atendimento humano.

        Chamado quando o bot escala e de novo a cada resposta que a loja digita
        pelo celular: enquanto houver gente falando, o bot continua calado.
        """
        self.slots["handoff_since"] = datetime.now(timezone.utc).isoformat()

    def handoff_idle_minutes(self) -> float:
        """Minutos desde o último sinal do atendimento humano.

        Sem marca (conversa que entrou em handoff antes desta versão) devolve
        infinito: melhor o bot reassumir do que deixar o cliente sem ninguém.
        """
        raw = self.slots.get("handoff_since")
        if not isinstance(raw, str):
            return float("inf")
        try:
            since = datetime.fromisoformat(raw)
        except ValueError:
            return float("inf")
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - since).total_seconds() / 60.0


# ---------------------------------------------------------------------------
# Serialização do JSONB
# ---------------------------------------------------------------------------

def _load_cart(raw: Any) -> Cart:
    """Aceita tanto `[itens]` (default do schema) quanto `{"items": [...]}`."""
    if raw is None or raw == "":
        return Cart()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("cart JSONB inválido, reiniciando carrinho")
            return Cart()
    try:
        if isinstance(raw, list):
            return Cart(items=raw)
        if isinstance(raw, dict):
            return Cart(items=raw.get("items", []))
    except Exception:  # dado antigo/incompatível não pode derrubar a conversa
        logger.warning("cart JSONB incompatível, reiniciando carrinho", exc_info=True)
    return Cart()


def _dump_cart(cart: Cart) -> str:
    """Serializa como lista de itens — é o formato do default '[]' da coluna."""
    payload = json.loads(cart.model_dump_json())
    return json.dumps(payload["items"], ensure_ascii=False)


def _load_slots(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _dump_slots(slots: dict[str, Any]) -> str:
    return json.dumps(slots, ensure_ascii=False, default=str)


def _as_state(raw: Any) -> ConversationState:
    try:
        return ConversationState(str(raw))
    except ValueError:
        logger.warning("estado desconhecido em conversations: %r", raw)
        return ConversationState.SAUDACAO


def _as_uuid(raw: Any) -> UUID | None:
    if raw is None:
        return None
    return raw if isinstance(raw, UUID) else UUID(str(raw))


def _expires_at() -> datetime:
    ttl = get_settings().session_ttl_minutes
    return datetime.now(timezone.utc) + timedelta(minutes=ttl)


# ---------------------------------------------------------------------------
# Leitura / escrita
# ---------------------------------------------------------------------------

_SELECT = """
    SELECT id, phone, channel, state, slots, cart, customer_id,
           active_order_id, handoff, fail_count, expires_at
    FROM conversations
"""


def _row_to_session(row: Any) -> ConversationSession:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return ConversationSession(
        id=_as_uuid(mapping["id"]),  # type: ignore[arg-type]
        phone=mapping["phone"],
        channel=mapping["channel"],
        state=_as_state(mapping["state"]),
        slots=_load_slots(mapping["slots"]),
        cart=_load_cart(mapping["cart"]),
        customer_id=_as_uuid(mapping["customer_id"]),
        active_order_id=_as_uuid(mapping["active_order_id"]),
        handoff=bool(mapping["handoff"]),
        fail_count=int(mapping["fail_count"] or 0),
    )


async def load_or_create(
    db: Any, phone: str, channel: str = DEFAULT_CHANNEL
) -> ConversationSession:
    """Busca a conversa do telefone/canal, criando se for a primeira mensagem.

    Sessão vencida (`expires_at` no passado) reinicia em SAUDACAO: um cliente
    que sumiu por uma hora e voltou não deve cair no meio de um carrinho antigo.
    """
    result = await db.execute(
        text(_SELECT + " WHERE phone = :phone AND channel = :channel"),
        {"phone": phone, "channel": channel},
    )
    row = result.first()

    if row is None:
        insert = await db.execute(
            text(
                """
                INSERT INTO conversations (phone, channel, state, slots, cart,
                                           last_message_at, expires_at)
                VALUES (:phone, :channel, :state, CAST(:slots AS jsonb),
                        CAST(:cart AS jsonb), now(), :expires_at)
                ON CONFLICT (phone, channel) DO UPDATE SET last_message_at = now()
                RETURNING id
                """
            ),
            {
                "phone": phone,
                "channel": channel,
                "state": ConversationState.SAUDACAO.value,
                "slots": "{}",
                "cart": "[]",
                "expires_at": _expires_at(),
            },
        )
        new_id = insert.scalar_one()
        return ConversationSession(
            id=_as_uuid(new_id),  # type: ignore[arg-type]
            phone=phone,
            channel=channel,
            state=ConversationState.SAUDACAO,
        )

    session = _row_to_session(row)
    expires_at = row._mapping["expires_at"]
    if _is_expired(expires_at):
        session.reset_flow()
    return session


def _is_expired(expires_at: Any) -> bool:
    if expires_at is None:
        return False
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)


async def save_session(db: Any, session: ConversationSession) -> None:
    """Persiste estado + slots + carrinho e renova o TTL da sessão."""
    await db.execute(
        text(
            """
            UPDATE conversations
               SET state = :state,
                   slots = CAST(:slots AS jsonb),
                   cart = CAST(:cart AS jsonb),
                   customer_id = :customer_id,
                   active_order_id = :active_order_id,
                   handoff = :handoff,
                   fail_count = :fail_count,
                   last_message_at = now(),
                   expires_at = :expires_at
             WHERE id = :id
            """
        ),
        {
            "id": session.id,
            "state": session.state.value,
            "slots": _dump_slots(session.slots),
            "cart": _dump_cart(session.cart),
            "customer_id": session.customer_id,
            "active_order_id": session.active_order_id,
            "handoff": session.handoff,
            "fail_count": session.fail_count,
            "expires_at": _expires_at(),
        },
    )


async def reset_session(
    db: Any, phone: str, channel: str = DEFAULT_CHANNEL
) -> ConversationSession:
    """Volta a conversa ao início — usado pelo simulador e pelo `/reset` da CLI."""
    session = await load_or_create(db, phone, channel)
    session.reset_flow()
    session.handoff = False
    await save_session(db, session)
    await db.execute(
        text("DELETE FROM conversation_messages WHERE conversation_id = :id"),
        {"id": session.id},
    )
    return session


async def find_by_active_order(db: Any, order_id: UUID) -> ConversationSession | None:
    """Localiza a conversa dona de um pedido — o webhook só conhece o order_id."""
    result = await db.execute(
        text(_SELECT + " WHERE active_order_id = :order_id LIMIT 1"),
        {"order_id": order_id},
    )
    row = result.first()
    return _row_to_session(row) if row is not None else None


# ---------------------------------------------------------------------------
# Log de mensagens
# ---------------------------------------------------------------------------

async def log_message(
    db: Any,
    *,
    conversation_id: UUID,
    direction: MessageDirection,
    content: str,
    state_before: ConversationState | None = None,
    state_after: ConversationState | None = None,
    detected_intent: str | None = None,
    confidence: float | None = None,
    llm_model: str | None = None,
    llm_usage: dict[str, Any] | None = None,
    provider_message_id: str | None = None,
) -> None:
    """Grava a mensagem (entrada ou saída) com os metadados de custo do LLM.

    `ON CONFLICT (provider_message_id) DO NOTHING` porque o eco de uma mensagem
    enviada pelo bot chega de volta pelo webhook do WhatsApp com o mesmo id —
    sem isso, toda resposta do bot apareceria duplicada no histórico.
    """
    await db.execute(
        text(
            """
            INSERT INTO conversation_messages (
                conversation_id, direction, content, state_before, state_after,
                detected_intent, confidence, llm_model, llm_usage,
                provider_message_id
            ) VALUES (
                :conversation_id, :direction, :content, :state_before, :state_after,
                :detected_intent, :confidence, :llm_model,
                CAST(:llm_usage AS jsonb), :provider_message_id
            )
            ON CONFLICT (provider_message_id) WHERE provider_message_id IS NOT NULL
            DO NOTHING
            """
        ),
        {
            "conversation_id": conversation_id,
            "direction": direction.value,
            "content": content,
            "state_before": state_before.value if state_before else None,
            "state_after": state_after.value if state_after else None,
            "detected_intent": detected_intent,
            "confidence": round(confidence, 3) if confidence is not None else None,
            "llm_model": llm_model,
            "llm_usage": json.dumps(llm_usage, default=str) if llm_usage else None,
            "provider_message_id": provider_message_id,
        },
    )


async def already_seen(db: Any, provider_message_id: str | None) -> bool:
    """A mensagem já foi atendida numa entrega anterior deste mesmo evento?

    O WhatsApp (e a Evolution no meio) entrega *pelo menos* uma vez: a mesma
    mensagem chega de novo quando o webhook demora ou devolve erro. Sem esta
    checagem o agente roda duas vezes — a segunda já com o estado adiantado
    pela primeira, respondendo "não entendi" a uma pergunta que ninguém fez e
    consumindo o contador de falhas até cair em atendimento humano.

    A entrada duplicada não aparece no painel (o `ON CONFLICT` de `log_message`
    a descarta), mas a resposta sai — foi o que confundiu o teste com cliente
    real. Quem decide é a mesma coluna única: se já existe, já foi atendida.
    """
    if not provider_message_id:
        return False
    result = await db.execute(
        text(
            "SELECT 1 FROM conversation_messages "
            "WHERE provider_message_id = :id LIMIT 1"
        ),
        {"id": provider_message_id},
    )
    return result.first() is not None


async def recent_turns(db: Any, conversation_id: UUID, limit: int = 8) -> list[Turn]:
    """Histórico curto para dar contexto ao LLM (mais antigo primeiro)."""
    result = await db.execute(
        text(
            """
            SELECT direction, content
            FROM conversation_messages
            WHERE conversation_id = :conversation_id
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
            """
        ),
        {"conversation_id": conversation_id, "limit": limit},
    )
    rows: Sequence[Any] = result.fetchall()
    turns = [
        Turn(
            role="cliente" if str(row[0]) == MessageDirection.ENTRADA.value else "agente",
            content=row[1],
        )
        for row in rows
    ]
    turns.reverse()
    return turns


# ---------------------------------------------------------------------------
# Dados do cliente (leitura oportunista — nunca derruba a conversa)
# ---------------------------------------------------------------------------

async def get_saved_address(db: Any, phone: str) -> dict[str, Any] | None:
    """Último endereço do cliente, para não pedir tudo de novo a quem já pediu."""
    try:
        result = await db.execute(
            text(
                """
                SELECT a.rua, a.numero, a.bairro, a.complemento, a.referencia
                FROM addresses a
                JOIN customers c ON c.id = a.customer_id
                WHERE c.phone = :phone
                ORDER BY a.is_default DESC, a.created_at DESC
                LIMIT 1
                """
            ),
            {"phone": phone},
        )
        row = result.first()
    except Exception:  # cliente novo, tabela vazia ou banco de teste
        logger.debug("não foi possível ler endereço salvo", exc_info=True)
        return None
    if row is None:
        return None
    return {
        "rua": row[0],
        "numero": row[1],
        "bairro": row[2],
        "complemento": row[3],
        "referencia": row[4],
    }

