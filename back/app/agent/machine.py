"""Máquina de estados do agente — quem realmente conduz o pedido.

O LLM só entrega `NluResult`. Todo o resto (qual o próximo estado, qual produto
existe, quanto custa, quando gerar o Pix) é decidido aqui, com o catálogo real
em mãos e preço em `Decimal`. Toda mudança de estado passa por
`assert_transition`, então pular etapa vira erro em vez de pedido furado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Awaitable, Callable, Sequence
from uuid import UUID

from app.agent import renderer as r
from app.agent.checkout import (
    AgentDeps,
    address_of,
    final_summary,
    missing_address_fields,
    order_status_reply,
    place_order,
    start_checkout,
)
from app.agent.llm import NluResult
from app.agent.resolver import (
    MatchStatus,
    pick_by_number,
    resolve_complement,
    resolve_product,
    split_queries,
)
from app.agent.session import ConversationSession
from app.agent.states import CANCELLABLE_STATES, advance as _go, can_transition
from app.domain.cart import CartComplement, CartItem
from app.domain.catalog import CatalogGroup, CatalogProduct, normalize
from app.domain.enums import ConversationState as S
from app.domain.enums import Intent

logger = logging.getLogger(__name__)

#: Palavras que valem como "chega, pode seguir" dentro de um grupo opcional.
_DONE_WORDS = frozenset({"nao", "nao quero", "so isso", "pronto", "chega", "ok", "e so isso"})


@dataclass(slots=True)
class MachineResult:
    replies: list[str] = field(default_factory=list)
    state: S = S.SAUDACAO


# ---------------------------------------------------------------------------
# Helpers de estado
# ---------------------------------------------------------------------------

def _offer(session: ConversationSession, ids: Sequence[Any]) -> None:
    """Registra a lista numerada que acabamos de mostrar (para aceitar "2")."""
    session.slots["options"] = [str(i) for i in ids]


def _offered(session: ConversationSession) -> list[str]:
    return list(session.slots.get("options") or [])


def _fail(session: ConversationSession, deps: AgentDeps) -> list[str]:
    """Incrementa o contador de incompreensão e escala para humano no limite."""
    session.fail_count += 1
    if session.fail_count >= deps.settings.max_nlu_failures:
        return _to_human(session)
    return [r.fallback(session.fail_count)]


def _back_to_choosing(session: ConversationSession) -> None:
    """Volta para a escolha de produto respeitando a tabela de transições."""
    if session.state is S.PERSONALIZANDO_ITEM:
        _go(session, S.REVISANDO_CARRINHO)
    elif session.state in {S.CANCELADO, S.CONCLUIDO}:
        _go(session, S.SAUDACAO)
    _go(session, S.ESCOLHENDO_PRODUTO)


def _to_human(session: ConversationSession) -> list[str]:
    if not can_transition(session.state, S.ATENDIMENTO_HUMANO):
        _go(session, S.SAUDACAO)  # de CANCELADO só se sai reabrindo a conversa
    _go(session, S.ATENDIMENTO_HUMANO)
    session.handoff = True
    session.slots.pop("options", None)
    return [r.handoff()]


def _clear_order(session: ConversationSession) -> None:
    """Esquece o pedido em construção, sem mexer no estado nem no cliente."""
    session.slots = {}
    session.cart.items.clear()
    session.active_order_id = None
    session.fail_count = 0


def _cancel(session: ConversationSession) -> list[str]:
    _go(session, S.CANCELADO)
    _clear_order(session)
    return [r.cancelled()]


def _menu_reply(deps: AgentDeps, session: ConversationSession) -> list[str]:
    _offer(session, [p.id for p in deps.catalog.available_products])
    return [r.menu(deps.catalog)]


# ---------------------------------------------------------------------------
# Item em construção (fica em slots["pending_item"])
# ---------------------------------------------------------------------------

def _start_item(
    session: ConversationSession, product: CatalogProduct, quantity: int
) -> None:
    session.slots["pending_item"] = {
        "product_id": str(product.id),
        "product_name": product.name,
        "unit_base_price": str(product.base_price),
        "quantity": max(1, quantity),
        "complements": [],
        "group_index": 0,
    }


def _pending(session: ConversationSession) -> dict[str, Any] | None:
    pending = session.slots.get("pending_item")
    return pending if isinstance(pending, dict) else None


def _pending_product(
    deps: AgentDeps, pending: dict[str, Any]
) -> CatalogProduct | None:
    return deps.catalog.product_by_id(UUID(pending["product_id"]))


def _current_group(
    deps: AgentDeps, pending: dict[str, Any]
) -> tuple[CatalogProduct | None, CatalogGroup | None]:
    product = _pending_product(deps, pending)
    if product is None:
        return None, None
    groups = product.required_groups
    index = int(pending.get("group_index", 0))
    if index >= len(groups):
        return product, None
    return product, groups[index]


def _chosen_in_group(pending: dict[str, Any], group: CatalogGroup) -> list[dict[str, Any]]:
    gid = str(group.id)
    return [c for c in pending["complements"] if c["group_id"] == gid]


def _commit_item(session: ConversationSession) -> CartItem:
    """Move o item em construção para o carrinho."""
    pending = session.slots.pop("pending_item")
    item = CartItem(
        product_id=UUID(pending["product_id"]),
        product_name=pending["product_name"],
        unit_base_price=Decimal(pending["unit_base_price"]),
        quantity=int(pending["quantity"]),
        complements=[
            CartComplement(
                id=UUID(c["id"]),
                group_id=UUID(c["group_id"]),
                name=c["name"],
                extra_price=Decimal(c["extra_price"]),
            )
            for c in pending["complements"]
        ],
    )
    session.cart.items.append(item)
    return item


def _finish_item(session: ConversationSession) -> list[str]:
    """Fecha o item em construção e leva a conversa para o carrinho."""
    item = _commit_item(session)
    _go(session, S.REVISANDO_CARRINHO)
    session.slots.pop("options", None)
    return [r.cart_added(item, session.cart)]


def _ask_group(
    deps: AgentDeps,
    session: ConversationSession,
    product: CatalogProduct,
    group: CatalogGroup,
    pending: dict[str, Any],
) -> list[str]:
    _offer(session, [c.id for c in group.available_complements])
    chosen = [c["name"] for c in _chosen_in_group(pending, group)]
    return [r.group_question(product, group, chosen)]


def _advance_group(
    deps: AgentDeps, session: ConversationSession, pending: dict[str, Any]
) -> list[str]:
    """Vai para o próximo grupo obrigatório ou fecha o item."""
    pending["group_index"] = int(pending.get("group_index", 0)) + 1
    product, group = _current_group(deps, pending)
    if product is None:  # produto saiu do cardápio no meio da conversa
        session.slots.pop("pending_item", None)
        _back_to_choosing(session)
        return [r.ask_product()]
    if group is not None:
        _go(session, S.PERSONALIZANDO_ITEM)
        return _ask_group(deps, session, product, group, pending)

    return _finish_item(session)


# ---------------------------------------------------------------------------
# Entrada do produto (usada por SAUDACAO e ESCOLHENDO_PRODUTO)
# ---------------------------------------------------------------------------

def _take_product(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    query = (nlu.product_query or text).strip()

    # Resposta numérica só vale contra a lista que acabamos de oferecer.
    chosen_id = pick_by_number(query, _offered(session))
    product: CatalogProduct | None = None
    if chosen_id:
        product = deps.catalog.product_by_id(UUID(chosen_id))

    if product is None:
        match = resolve_product(query, deps.catalog)
        if match.status is MatchStatus.NOT_FOUND:
            _go(session, S.ESCOLHENDO_PRODUTO)
            return _fail(session, deps)
        if match.status is MatchStatus.AMBIGUOUS:
            _go(session, S.ESCOLHENDO_PRODUTO)
            _offer(session, [p.id for p in match.candidates])
            return [r.product_ambiguous(match.candidates)]
        if match.status is MatchStatus.UNAVAILABLE:
            _go(session, S.ESCOLHENDO_PRODUTO)
            name = match.candidates[0].name if match.candidates else query
            return [r.product_unavailable(name)]
        product = match.product

    assert product is not None
    session.fail_count = 0
    _start_item(session, product, nlu.quantity or 1)
    pending = session.slots["pending_item"]

    _, group = _current_group(deps, pending)
    if group is not None:
        _go(session, S.PERSONALIZANDO_ITEM)
        # O cliente já pode ter mandado os sabores junto ("pote com pistache").
        if nlu.complement_queries:
            return _take_complements(deps, session, nlu.complement_queries)
        return _ask_group(deps, session, product, group, pending)

    return _finish_item(session)


def _take_complements(
    deps: AgentDeps,
    session: ConversationSession,
    queries: Sequence[str],
) -> list[str]:
    """Aplica escolhas ao grupo corrente, respeitando min/max."""
    pending = _pending(session)
    if pending is None:
        _back_to_choosing(session)
        return [r.ask_product()]

    product, group = _current_group(deps, pending)
    if product is None or group is None:
        return _advance_group(deps, session, pending)

    problems: list[str] = []
    added = 0
    for query in queries:
        chosen = _chosen_in_group(pending, group)
        if len(chosen) >= group.max_choices:
            problems.append(r.too_many_choices(group))
            break

        complement = None
        chosen_id = pick_by_number(query, _offered(session))
        if chosen_id:
            candidate = deps.catalog.complement_by_id(UUID(chosen_id))
            if candidate is not None and candidate.group_id == group.id:
                complement = candidate

        if complement is None:
            match = resolve_complement(query, group)
            if match.status is MatchStatus.NOT_FOUND:
                problems.append(r.complement_not_found(query, group))
                continue
            if match.status is MatchStatus.AMBIGUOUS:
                _offer(session, [c.id for c in match.candidates])
                problems.append(r.complement_ambiguous(match.candidates))
                continue
            if match.status is MatchStatus.UNAVAILABLE:
                name = match.candidates[0].name if match.candidates else query
                problems.append(r.complement_unavailable(name))
                continue
            complement = match.complement

        assert complement is not None
        pending["complements"].append(
            {
                "id": str(complement.id),
                "group_id": str(complement.group_id),
                "name": complement.name,
                "extra_price": str(complement.extra_price),
            }
        )
        added += 1

    if added:
        session.fail_count = 0
    else:
        # Nada aproveitado neste turno. Sem contar como falha, o cliente que
        # não consegue se fazer entender ficaria preso no grupo para sempre.
        session.fail_count += 1
        if session.fail_count >= deps.settings.max_nlu_failures:
            return problems + _to_human(session)

    chosen = _chosen_in_group(pending, group)
    if len(chosen) >= group.min_choices and len(chosen) >= group.max_choices:
        return problems + _advance_group(deps, session, pending)
    if len(chosen) >= group.min_choices and group.min_choices > 0:
        # Mínimo satisfeito mas ainda cabe mais: pergunta se quer completar.
        _go(session, S.PERSONALIZANDO_ITEM)
        return problems + [r.group_extra_choice(group, [c["name"] for c in chosen])]

    _go(session, S.PERSONALIZANDO_ITEM)
    if not added and not problems:
        return [r.fallback(session.fail_count)]
    # Escolha aceita mas o grupo ainda não fechou (ex.: 1 de 3 sabores):
    # repetir a pergunta mostra "Já anotei… Faltam 2". Responder o texto de
    # incompreensão aqui diria que o bot não entendeu algo que ele entendeu.
    return problems + _ask_group(deps, session, product, group, pending)


# ---------------------------------------------------------------------------
# Handlers por estado
# ---------------------------------------------------------------------------

async def _handle_saudacao(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    _go(session, S.ESCOLHENDO_PRODUTO)
    replies = [r.greeting()] + _menu_reply(deps, session)
    if nlu.intent is Intent.ESCOLHER_PRODUTO and (nlu.product_query or "").strip():
        return replies[:1] + _take_product(deps, session, nlu, text)
    return replies


async def _handle_escolhendo_produto(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    if nlu.intent is Intent.FINALIZAR_PEDIDO:
        if session.cart.is_empty:
            return [r.cart_empty_on_close()]
        _go(session, S.REVISANDO_CARRINHO)
        return await start_checkout(deps, session)

    if nlu.intent in {Intent.NEGAR, Intent.CONFIRMAR} and not session.cart.is_empty:
        _go(session, S.REVISANDO_CARRINHO)
        return [r.ask_more_or_close(session.cart)]

    if nlu.intent is Intent.DESCONHECIDO and not (nlu.product_query or "").strip():
        return _fail(session, deps)

    return _take_product(deps, session, nlu, text)


async def _handle_personalizando(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    pending = _pending(session)
    if pending is None:
        _back_to_choosing(session)
        return [r.ask_product()]

    product, group = _current_group(deps, pending)
    if product is None or group is None:
        return _advance_group(deps, session, pending)

    chosen = _chosen_in_group(pending, group)
    normalized = normalize(text)

    # "não / é só isso" fecha o grupo, desde que o mínimo esteja satisfeito.
    said_done = nlu.intent in {Intent.NEGAR, Intent.FINALIZAR_PEDIDO} or normalized in _DONE_WORDS
    if said_done and len(chosen) >= group.min_choices:
        return _advance_group(deps, session, pending)
    if nlu.intent is Intent.CONFIRMAR and len(chosen) >= group.min_choices:
        return _advance_group(deps, session, pending)

    queries = list(nlu.complement_queries)
    if not queries:
        raw = (nlu.product_query or text).strip()
        queries = split_queries(raw) if raw else []
    if not queries:
        return _fail(session, deps)

    return _take_complements(deps, session, queries)


async def _handle_revisando(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    if nlu.intent in {Intent.FINALIZAR_PEDIDO, Intent.CONFIRMAR}:
        if session.cart.is_empty:
            _go(session, S.ESCOLHENDO_PRODUTO)
            return [r.cart_empty_on_close()]
        return await start_checkout(deps, session)

    if nlu.intent in {Intent.ADICIONAR_MAIS, Intent.NEGAR} and not (
        nlu.product_query or ""
    ).strip():
        _go(session, S.ESCOLHENDO_PRODUTO)
        return _menu_reply(deps, session)

    if nlu.intent is Intent.ESCOLHER_PRODUTO or (nlu.product_query or "").strip():
        _go(session, S.ESCOLHENDO_PRODUTO)
        return _take_product(deps, session, nlu, text)

    if nlu.intent is Intent.INFORMAR_ENDERECO and nlu.address is not None:
        _merge_address(session, nlu)
        return await start_checkout(deps, session)

    return _fail(session, deps)


def _merge_address(session: ConversationSession, nlu: NluResult) -> None:
    address = address_of(session)
    if nlu.address is not None:
        for key, value in nlu.address.model_dump().items():
            if value:
                address[key] = value
    session.slots["address"] = address


async def _handle_endereco(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    # Confirmação do endereço salvo do cliente.
    if session.slots.get("address_needs_confirm"):
        if nlu.intent is Intent.CONFIRMAR:
            session.slots.pop("address_needs_confirm", None)
            _go(session, S.CONFIRMANDO_PEDIDO)
            return [final_summary(deps, session)]
        if nlu.intent is Intent.NEGAR:
            session.slots.pop("address_needs_confirm", None)
            session.slots["address"] = {}
            _go(session, S.COLETANDO_ENDERECO)
            return [r.ask_address(["rua", "numero", "bairro"])]
        session.slots.pop("address_needs_confirm", None)

    before = address_of(session)
    _merge_address(session, nlu)
    address = address_of(session)

    if address == before and nlu.address is None:
        # Nada de novo veio: pode ser resposta solta ("Centro") para o campo que falta.
        missing = missing_address_fields(address)
        if len(missing) == 1 and text.strip():
            address[missing[0]] = text.strip()
            session.slots["address"] = address

    missing = missing_address_fields(address_of(session))
    if missing:
        _go(session, S.COLETANDO_ENDERECO)
        if nlu.address is None and not text.strip():
            return _fail(session, deps)
        return [r.ask_address(missing)]

    session.fail_count = 0
    if nlu.customer_name:
        session.slots["customer_name"] = nlu.customer_name
    _go(session, S.CONFIRMANDO_PEDIDO)
    return [final_summary(deps, session)]


async def _handle_confirmando(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    # FINALIZAR_PEDIDO entra aqui porque a IA às vezes classifica um "sim" à
    # pergunta de confirmação como "quer fechar o pedido" em vez de CONFIRMAR
    # (visto em produção) — nesta tela os dois significam a mesma coisa.
    if nlu.intent in {Intent.CONFIRMAR, Intent.FINALIZAR_PEDIDO}:
        return await place_order(deps, session)

    if nlu.intent in {Intent.NEGAR, Intent.ADICIONAR_MAIS} or (
        nlu.product_query or ""
    ).strip():
        _go(session, S.REVISANDO_CARRINHO)
        if (nlu.product_query or "").strip():
            _go(session, S.ESCOLHENDO_PRODUTO)
            return _take_product(deps, session, nlu, text)
        return [r.ask_more_or_close(session.cart)]

    if nlu.intent is Intent.INFORMAR_ENDERECO and nlu.address is not None:
        _merge_address(session, nlu)
        _go(session, S.CONFIRMANDO_PEDIDO)
        return [final_summary(deps, session)]

    _go(session, S.CONFIRMANDO_PEDIDO)
    return _fail(session, deps)


async def _handle_aguardando(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    """Estado passivo: quem tira daqui é o webhook de pagamento."""
    _go(session, S.AGUARDANDO_PAGAMENTO)
    return await order_status_reply(deps, session)


async def _handle_terminal(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult, text: str
) -> list[str]:
    """CONCLUIDO/CANCELADO: qualquer mensagem nova recomeça a conversa."""
    _go(session, S.SAUDACAO)
    _clear_order(session)
    return await _handle_saudacao(deps, session, nlu, text)


_HANDLERS: dict[S, Callable[..., Awaitable[list[str]]]] = {
    S.SAUDACAO: _handle_saudacao,
    S.ESCOLHENDO_PRODUTO: _handle_escolhendo_produto,
    S.PERSONALIZANDO_ITEM: _handle_personalizando,
    S.REVISANDO_CARRINHO: _handle_revisando,
    S.COLETANDO_ENDERECO: _handle_endereco,
    S.CONFIRMANDO_PEDIDO: _handle_confirmando,
    S.AGUARDANDO_PAGAMENTO: _handle_aguardando,
    S.CONCLUIDO: _handle_terminal,
    S.CANCELADO: _handle_terminal,
}


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

async def run(
    deps: AgentDeps,
    session: ConversationSession,
    nlu: NluResult,
    text: str,
) -> MachineResult:
    """Roda um turno: intenções globais primeiro, depois o handler do estado."""
    if session.state is S.ATENDIMENTO_HUMANO:
        # Conversa está com o time; o bot fica calado.
        return MachineResult([], session.state)

    globals_reply = await _handle_global_intents(deps, session, nlu)
    if globals_reply is not None:
        return MachineResult(globals_reply, session.state)

    handler = _HANDLERS.get(session.state)
    if handler is None:  # estado novo sem handler é bug, não silêncio
        logger.error("sem handler para o estado %s", session.state)
        return MachineResult([r.fallback(2)], session.state)

    replies = await handler(deps, session, nlu, text)
    return MachineResult([reply for reply in replies if reply], session.state)


async def _handle_global_intents(
    deps: AgentDeps, session: ConversationSession, nlu: NluResult
) -> list[str] | None:
    """Intenções que valem em qualquer estado, antes do handler específico."""
    if nlu.intent is Intent.FALAR_COM_HUMANO:
        return _to_human(session)

    if nlu.intent is Intent.CANCELAR:
        if session.state in CANCELLABLE_STATES:
            return _cancel(session)
        return [r.cancelled()]

    if nlu.intent is Intent.VER_CARDAPIO:
        # No meio da personalização ou do pagamento, mostrar o cardápio não
        # pode desmontar o item em construção: só mostra e fica onde está.
        if session.state in {S.SAUDACAO, S.CANCELADO, S.CONCLUIDO}:
            _back_to_choosing(session)
        return _menu_reply(deps, session)

    if nlu.intent is Intent.CONSULTAR_STATUS and session.active_order_id is not None:
        return await order_status_reply(deps, session)

    return None
