"""Executor: aplica ao pedido as operações que a IA entendeu.

A divisão de trabalho, que é o ponto do desenho:

    mensagem → LLM → operações → ESTE MÓDULO → estado do pedido
                                      ↓
                              catálogo + Decimal
                                      ↓
                                  resposta

A IA tem liberdade para interpretar linguagem natural e dizer *qual operação*
o cliente quer. Ela não tem autoridade para inventar produto, preço, taxa ou
disponibilidade, nem para cobrar: cada operação é validada aqui contra o
catálogo real, e só uma confirmação explícita sobre um resumo que o cliente
viu gera Pix.

O que mudou em relação à versão anterior, e por quê:

- **Editar deixou de ser adicionar.** Havia uma operação só (escolher
  produto), então "troca chocolate por fior di latte" e "remove o item 1"
  viravam item novo — cada tentativa de corrigir o pedido aumentava a conta.
- **O item em construção é um rascunho mutável.** "pote médio" → "pistache" →
  "não, troca por chocolate" → "na verdade quero o grande" mexem todos no
  mesmo objeto.
- **Pergunta não derruba o fluxo.** `ANSWER_QUESTION` responde e devolve o
  cliente exatamente para onde ele estava.
- **A etapa do diálogo saiu dos estados e foi para os slots.** Restaram os
  estados que carregam garantia (ver `states.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from app.agent import faq
from app.agent import renderer as r
from app.agent.checkout import (
    AgentDeps,
    address_of,
    final_summary,
    fulfillment_of,
    missing_address_fields,
    order_status_reply,
    place_order,
    set_fulfillment,
)
from app.agent.plan import Action, AgentPlan, Operation
from app.agent.resolver import MatchStatus, resolve_product
from app.agent.session import ConversationSession
from app.agent.states import CANCELLABLE_STATES, advance as _go, can_transition
from app.core.config import get_settings
from app.domain.cart import CartComplement, CartItem
from app.domain.catalog import CatalogGroup, CatalogProduct, normalize
from app.domain.enums import ConversationState as S
from app.domain.enums import FulfillmentType

logger = logging.getLogger(__name__)

#: Slots usados pelo executor.
DRAFT = "draft"                      # item em construção (rascunho mutável)
CLOSING = "closing"                  # o cliente já disse que quer fechar
AWAITING_CONFIRM = "awaiting_confirm"  # resumo final na tela, esperando "sim"
LAST_OFFER = "last_offer"            # a última lista numerada que mostramos


@dataclass
class _Turn:
    """O que aconteceu neste turno, para compor UMA resposta no fim.

    Sem isto o bot responde uma mensagem por operação e vira metralhadora:
    "Tirei o X." / "Adicionei o Y." / "Anotei entrega." / "Qual o endereço?".
    """

    notes: list[str] = field(default_factory=list)   # o que o bot confirma/responde
    changed: bool = False                            # mexeu no pedido?
    answered: bool = False                           # respondeu pergunta?
    finished: list[str] | None = None                # resposta final (Pix, cancelamento)

    def say(self, *texts: str) -> None:
        self.notes.extend(t for t in texts if t)


# ---------------------------------------------------------------------------
# Rascunho do item (slots["draft"])
# ---------------------------------------------------------------------------

def _draft(session: ConversationSession) -> dict[str, Any] | None:
    draft = session.slots.get(DRAFT)
    return draft if isinstance(draft, dict) else None


def _start_draft(
    session: ConversationSession, product: CatalogProduct, quantity: int = 1
) -> dict[str, Any]:
    draft = {
        "product_id": str(product.id),
        "product_name": product.name,
        "unit_base_price": str(product.base_price),
        "quantity": max(1, quantity),
        "flavors": [],
    }
    session.slots[DRAFT] = draft
    return draft


def _draft_product(deps: AgentDeps, draft: dict[str, Any]) -> CatalogProduct | None:
    return deps.catalog.product_by_id(UUID(draft["product_id"]))


def _first_open_group(
    deps: AgentDeps, draft: dict[str, Any]
) -> tuple[CatalogProduct | None, CatalogGroup | None]:
    """O grupo obrigatório que ainda não fechou, se houver."""
    product = _draft_product(deps, draft)
    if product is None:
        return None, None
    for group in product.required_groups:
        escolhidos = [f for f in draft["flavors"] if f["group_id"] == str(group.id)]
        if len(escolhidos) < group.min_choices:
            return product, group
    return product, None


def _draft_complete(deps: AgentDeps, draft: dict[str, Any]) -> bool:
    _, group = _first_open_group(deps, draft)
    return group is None


def _commit_draft(deps: AgentDeps, session: ConversationSession) -> CartItem | None:
    """Move o rascunho para o carrinho. Só quando ele está completo."""
    draft = _draft(session)
    if draft is None or not _draft_complete(deps, draft):
        return None
    item = CartItem(
        product_id=UUID(draft["product_id"]),
        product_name=draft["product_name"],
        unit_base_price=Decimal(draft["unit_base_price"]),
        quantity=int(draft["quantity"]),
        complements=[
            CartComplement(
                id=UUID(f["id"]),
                group_id=UUID(f["group_id"]),
                name=f["name"],
                extra_price=Decimal(f["extra_price"]),
            )
            for f in draft["flavors"]
        ],
    )
    session.cart.items.append(item)
    session.slots.pop(DRAFT, None)
    return item


# ---------------------------------------------------------------------------
# Alvos (qual item a operação atinge)
# ---------------------------------------------------------------------------

def _target_index(session: ConversationSession, op: Operation) -> int | None:
    """Qual item do carrinho a operação aponta, contando a partir de 1."""
    itens = session.cart.items
    if not itens:
        return None

    if op.item_index is not None and 1 <= op.item_index <= len(itens):
        return op.item_index - 1

    if op.product_name:
        alvo = normalize(op.product_name)
        achados = [i for i, item in enumerate(itens) if normalize(item.product_name) == alvo]
        if len(achados) == 1:
            return achados[0]
        if achados:
            return achados[-1]  # dois iguais: mexe no último, como gente espera

    if len(itens) == 1:
        return 0
    return None


def _group_of(deps: AgentDeps, item: CartItem) -> CatalogGroup | None:
    product = deps.catalog.product_by_id(item.product_id)
    if product is None:
        return None
    return product.required_groups[0] if product.required_groups else None


# ---------------------------------------------------------------------------
# Resolução de nomes (a IA propõe, o catálogo decide)
# ---------------------------------------------------------------------------

def _find_product(deps: AgentDeps, op: Operation) -> tuple[CatalogProduct | None, str | None]:
    """Produto da operação, ou o motivo de não ter dado.

    Devolve `(produto, problema)`. O nome vem da IA, mas quem diz se existe,
    se está disponível e se é ambíguo é o catálogo.
    """
    nome = (op.product_name or "").strip()
    if nome:
        product = deps.catalog.product_by_name(nome)
        if product is not None:
            if not product.is_available:
                return None, r.product_unavailable(product.name)
            return product, None

    texto = (op.raw_text or op.product_name or "").strip()
    if not texto:
        return None, None

    match = resolve_product(texto, deps.catalog)
    if match.ok:
        return match.product, None
    if match.status is MatchStatus.AMBIGUOUS:
        return None, r.product_ambiguous(match.candidates)
    if match.status is MatchStatus.UNAVAILABLE:
        nome_ = match.candidates[0].name if match.candidates else texto
        return None, r.product_unavailable(nome_)
    return None, r.product_not_found(texto)


def _find_flavors(
    group: CatalogGroup, nomes: Sequence[str]
) -> tuple[list[Any], list[str]]:
    """Casa nomes de sabor com o grupo. Devolve (achados, problemas)."""
    achados, problemas = [], []
    for nome in nomes:
        alvo = normalize(nome)
        escolha = next(
            (c for c in group.complements if normalize(c.name) == alvo), None
        )
        if escolha is None:
            problemas.append(r.complement_not_found(nome, group))
            continue
        if not escolha.is_available:
            problemas.append(r.complement_unavailable(escolha.name))
            continue
        achados.append(escolha)
    return achados, problemas


def _apply_flavors(
    draft_or_item: Any,
    group: CatalogGroup,
    *,
    add: Sequence[Any],
    remove_names: Sequence[str],
    turn: _Turn,
    is_draft: bool,
) -> None:
    """Tira e põe sabores no MESMO item, respeitando o máximo e sem repetir."""
    atuais: list[Any] = draft_or_item["flavors"] if is_draft else draft_or_item.complements
    repetidos: list[str] = []
    mexeu = False

    # Remoções primeiro: é o que faz "troca X por Y" caber no mesmo item.
    for nome in remove_names:
        alvo = normalize(nome)
        for atual in list(atuais):
            nome_atual = atual["name"] if is_draft else atual.name
            if normalize(nome_atual) == alvo:
                atuais.remove(atual)
                turn.say(r.flavor_removed(nome_atual))
                turn.changed = True
                mexeu = True
                break

    for escolha in add:
        if len(atuais) >= group.max_choices:
            turn.say(r.group_full(group))
            break
        ids = [
            (f["id"] if is_draft else str(f.id)) for f in atuais
        ]
        if str(escolha.id) in ids:
            # Sabor não se repete no mesmo pote. O modelo costuma REPETIR os
            # já escolhidos junto com o novo ("troca morango por chocolate"
            # volta com Pistache também): aí a repetição é só ruído e some.
            # Só vira aviso quando foi o cliente que pediu duas vezes.
            repetidos.append(escolha.name)
            continue
        if is_draft:
            atuais.append(
                {
                    "id": str(escolha.id),
                    "group_id": str(escolha.group_id),
                    "name": escolha.name,
                    "extra_price": str(escolha.extra_price),
                }
            )
        else:
            atuais.append(
                CartComplement(
                    id=escolha.id,
                    group_id=escolha.group_id,
                    name=escolha.name,
                    extra_price=escolha.extra_price,
                )
            )
        turn.changed = True
        mexeu = True

    if repetidos and not mexeu:
        turn.say(r.flavor_already_chosen(repetidos[0]))


# ---------------------------------------------------------------------------
# As operações
# ---------------------------------------------------------------------------

async def _apply(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: _Turn
) -> None:
    """Aplica UMA operação. Nada aqui responde ao cliente diretamente."""
    action = op.action

    # O modelo costuma pendurar a forma de entrega e o endereço na MESMA
    # operação do item ("quero um pote G, vou retirar"). Lidos só na operação
    # dedicada, eles se perdiam e o bot perguntava de novo lá na frente.
    if op.fulfillment and action is not Action.SET_FULFILLMENT:
        _set_fulfillment(session, op.fulfillment, turn)
    if op.address is not None and action is not Action.UPDATE_ADDRESS:
        _merge_address(session, op.address, turn)

    if action is Action.ADD_ITEM:
        _op_add_item(deps, session, op, turn)

    elif action in {Action.UPDATE_ITEM, Action.REPLACE_ITEM}:
        _op_update_item(deps, session, op, turn)

    elif action is Action.REMOVE_ITEM:
        _op_remove_item(deps, session, op, turn)

    elif action is Action.UPDATE_QUANTITY:
        _op_quantity(deps, session, op, turn)

    elif action is Action.DUPLICATE_ITEM:
        _op_duplicate(deps, session, op, turn)

    elif action is Action.SET_FULFILLMENT:
        _set_fulfillment(session, op.fulfillment, turn)

    elif action is Action.UPDATE_ADDRESS:
        _merge_address(session, op.address, turn)

    elif action is Action.SHOW_MENU:
        turn.say(_menu(deps, session))
        turn.answered = True

    elif action is Action.SHOW_CART:
        turn.say(
            r.cart_summary(session.cart)
            if not session.cart.is_empty
            else r.cart_empty()
        )
        turn.answered = True

    elif action is Action.SHOW_TOTAL:
        turn.say(_total_reply(deps, session))
        turn.answered = True

    elif action is Action.ANSWER_QUESTION:
        turn.say(_answer_question(deps, session, op))
        turn.answered = True

    elif action is Action.CLOSE_ORDER:
        session.slots[CLOSING] = True

    elif action is Action.CANCEL_ORDER:
        turn.finished = _cancel(session)

    elif action is Action.REQUEST_HUMAN:
        turn.finished = _to_human(session)

    elif action is Action.ASK_CLARIFICATION:
        turn.say(op.clarification or r.ask_clarification())
        turn.answered = True

    # CONFIRM_ORDER e NO_ACTION são tratados em `run`: um mexe em dinheiro, o
    # outro é a ausência de operação.


def _set_fulfillment(session: ConversationSession, escolha: str | None, turn: _Turn) -> None:
    if escolha == "retirada":
        set_fulfillment(session, FulfillmentType.RETIRADA)
        turn.changed = True
    elif escolha == "entrega":
        set_fulfillment(session, FulfillmentType.ENTREGA)
        turn.changed = True


def _merge_address(session: ConversationSession, address: Any, turn: _Turn) -> None:
    """Endereço é objeto: o cliente completa em qualquer ordem, em qualquer turno."""
    if address is None:
        return
    endereco = address_of(session)
    for campo, valor in address.model_dump().items():
        if valor:
            endereco[campo] = valor
    session.slots["address"] = endereco
    set_fulfillment(session, FulfillmentType.ENTREGA)
    turn.changed = True


def _op_add_item(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: _Turn
) -> None:
    product, problema = _find_product(deps, op)
    if product is None:
        if problema:
            turn.say(problema)
            turn.answered = True
        return

    # Já havia um rascunho? Se estava incompleto, o cliente está trocando de
    # ideia sobre ele ("na verdade quero o médio"); se estava completo, ele
    # entra no carrinho e começamos outro.
    draft = _draft(session)
    if draft is not None:
        if _draft_complete(deps, draft):
            item = _commit_draft(deps, session)
            if item is not None:
                turn.say(r.item_added(item))
        elif str(product.id) != draft["product_id"]:
            antigo = draft["product_name"]
            _replace_draft_product(deps, session, draft, product, turn)
            turn.say(r.product_switched(antigo, product.name))
            _add_flavors_to_draft(deps, session, op, turn)
            return

    novo = _start_draft(session, product, op.quantity or 1)
    turn.changed = True
    if not product.required_groups:
        item = _commit_draft(deps, session)
        if item is not None:
            turn.say(r.item_added(item))
        return
    _add_flavors_to_draft(deps, session, op, turn, draft=novo)


def _add_flavors_to_draft(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    turn: _Turn,
    draft: dict[str, Any] | None = None,
) -> None:
    draft = draft or _draft(session)
    if draft is None or not (op.add_flavors or op.remove_flavors):
        return
    product, group = _first_open_group(deps, draft)
    if group is None:
        return
    achados, problemas = _find_flavors(group, op.add_flavors)
    turn.say(*problemas)
    _apply_flavors(
        draft,
        group,
        add=achados,
        remove_names=op.remove_flavors,
        turn=turn,
        is_draft=True,
    )


def _replace_draft_product(
    deps: AgentDeps,
    session: ConversationSession,
    draft: dict[str, Any],
    product: CatalogProduct,
    turn: _Turn,
) -> None:
    """Troca o produto do rascunho mantendo os sabores que ainda existem."""
    antigos = [f["name"] for f in draft["flavors"]]
    novo = _start_draft(session, product, int(draft.get("quantity", 1)))
    _, group = _first_open_group(deps, novo)
    if group is not None and antigos:
        achados, _ = _find_flavors(group, antigos)
        _apply_flavors(
            novo, group, add=achados, remove_names=[], turn=turn, is_draft=True
        )
    turn.changed = True


def _op_update_item(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: _Turn
) -> None:
    """Mexe num item que já existe — nunca cria um novo."""
    draft = _draft(session)

    # Trocar o produto (replace) tem prioridade sobre mexer em sabor.
    if op.action is Action.REPLACE_ITEM or (
        op.product_name and not op.add_flavors and not op.remove_flavors
    ):
        product, problema = _find_product(deps, op)
        if product is None:
            if problema:
                turn.say(problema)
                turn.answered = True
            return
        if draft is not None:
            antigo = draft["product_name"]
            if str(product.id) != draft["product_id"]:
                _replace_draft_product(deps, session, draft, product, turn)
                turn.say(r.product_switched(antigo, product.name))
            return
        index = _target_index(session, op)
        if index is None:
            turn.say(r.ask_which_item(session.cart))
            turn.answered = True
            return
        antigo = session.cart.items[index]
        session.cart.items.pop(index)
        novo = _start_draft(session, product, antigo.quantity)
        _, group = _first_open_group(deps, novo)
        if group is not None and antigo.complements:
            achados, _ = _find_flavors(group, [c.name for c in antigo.complements])
            _apply_flavors(
                novo, group, add=achados, remove_names=[], turn=turn, is_draft=True
            )
        turn.say(r.product_switched(antigo.product_name, product.name))
        turn.changed = True
        return

    # Mexer em sabor: no rascunho, se houver; senão no item do carrinho.
    if draft is not None:
        _add_flavors_to_draft(deps, session, op, turn)
        return

    index = _target_index(session, op)
    if index is None:
        turn.say(r.ask_which_item(session.cart))
        turn.answered = True
        return

    item = session.cart.items[index]
    group = _group_of(deps, item)
    if group is None:
        turn.say(r.item_has_no_flavors(item.product_name))
        turn.answered = True
        return

    achados, problemas = _find_flavors(group, op.add_flavors)
    turn.say(*problemas)
    _apply_flavors(
        item,
        group,
        add=achados,
        remove_names=op.remove_flavors,
        turn=turn,
        is_draft=False,
    )
    if turn.changed:
        turn.say(r.item_updated(item))


def _op_remove_item(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: _Turn
) -> None:
    # "tira o pistache" com um rascunho aberto é tirar o sabor, não o item.
    draft = _draft(session)
    if draft is not None and op.remove_flavors:
        product, group = _first_open_group(deps, draft)
        if group is not None:
            _apply_flavors(
                draft,
                group,
                add=[],
                remove_names=op.remove_flavors,
                turn=turn,
                is_draft=True,
            )
            return

    if session.cart.is_empty:
        if draft is not None:
            session.slots.pop(DRAFT, None)
            turn.say(r.item_removed(draft["product_name"]))
            turn.changed = True
            return
        turn.say(r.cart_empty())
        turn.answered = True
        return

    index = _target_index(session, op)
    if index is None:
        turn.say(r.ask_which_item(session.cart))
        turn.answered = True
        return

    removido = session.cart.items.pop(index)
    turn.say(r.item_removed(removido.product_name))
    turn.changed = True


def _op_quantity(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: _Turn
) -> None:
    if op.quantity is None:
        return

    draft = _draft(session)
    if draft is not None and op.item_index is None:
        draft["quantity"] = op.quantity
        turn.changed = True
        return

    index = _target_index(session, op)
    if index is None:
        turn.say(r.ask_which_item(session.cart))
        turn.answered = True
        return

    item = session.cart.items[index]
    item.quantity = op.quantity
    turn.say(r.quantity_updated(item))
    turn.changed = True


def _op_duplicate(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: _Turn
) -> None:
    # "põe também 2 cascões" chega do modelo como duplicate_item com o nome de
    # OUTRO produto. Duplicar aí repetiria o pote de R$ 50 que já estava no
    # carrinho. Quando o nome é de outro item, isto é adicionar, não duplicar.
    if op.product_name:
        alvo = deps.catalog.product_by_name(op.product_name)
        atual = (
            session.cart.items[_target_index(session, Operation(action=op.action)) or 0]
            if session.cart.items
            else None
        )
        if alvo is not None and (atual is None or alvo.id != atual.product_id):
            _op_add_item(deps, session, op, turn)
            return

    if session.cart.is_empty:
        turn.say(r.cart_empty())
        turn.answered = True
        return
    index = _target_index(session, op) if op.item_index or op.product_name else len(
        session.cart.items
    ) - 1
    if index is None:
        index = len(session.cart.items) - 1
    copia = session.cart.items[index].model_copy(deep=True)
    copia.quantity = op.quantity or 1
    session.cart.items.append(copia)
    turn.say(r.item_added(copia))
    turn.changed = True


# ---------------------------------------------------------------------------
# Respostas que só leem
# ---------------------------------------------------------------------------

def _menu(deps: AgentDeps, session: ConversationSession) -> str:
    session.slots[LAST_OFFER] = [p.name for p in deps.catalog.available_products]
    return r.menu(deps.catalog)


def _total_reply(deps: AgentDeps, session: ConversationSession) -> str:
    if session.cart.is_empty:
        return r.cart_empty()
    kind = fulfillment_of(session)
    taxa = (
        Decimal("0")
        if kind is FulfillmentType.RETIRADA
        else deps.settings.delivery_fee
    )
    return r.total_reply(session.cart, taxa, is_pickup=kind is FulfillmentType.RETIRADA)


def _answer_question(
    deps: AgentDeps, session: ConversationSession, op: Operation
) -> str:
    return faq.answer(
        topic=op.question_topic,
        question=op.question_text or "",
        raw_text=op.raw_text,
        catalog=deps.catalog,
        settings=deps.settings,
        cart=session.cart,
    )


# ---------------------------------------------------------------------------
# Atendimento humano
# ---------------------------------------------------------------------------

def _to_human(session: ConversationSession) -> list[str]:
    if not can_transition(session.state, S.ATENDIMENTO_HUMANO):
        _go(session, S.CONVERSANDO)
    _go(session, S.ATENDIMENTO_HUMANO)
    session.handoff = True
    session.touch_handoff()
    return [r.handoff()]


def human_on_the_line(session: ConversationSession) -> bool:
    """Alguém da loja deu sinal de vida há pouco tempo."""
    if not session.handoff and session.state is not S.ATENDIMENTO_HUMANO:
        return False
    return session.handoff_idle_minutes() < get_settings().handoff_return_minutes


def _resume_from_human(session: ConversationSession) -> None:
    session.handoff = False
    session.slots.pop("handoff_since", None)
    session.fail_count = 0
    if session.state is S.ATENDIMENTO_HUMANO:
        _go(session, S.CONVERSANDO)


def _handoff_turn(session: ConversationSession, plan: AgentPlan) -> list[str] | None:
    """Em atendimento humano o bot não conduz o pedido — mas não emudece.

    Devolve `None` quando o cliente mostrou que quer seguir com o bot: aí a
    conversa volta e o turno é processado normalmente, sem obrigar o cliente a
    repetir o que acabou de pedir.

    Ficar mudo era o defeito mais caro do agente: quem pedia atendente (ou
    caía lá por engano) não recebia mais nada, nem "estou chamando alguém",
    nem resposta a "cancela". Aqui ele continua ouvindo: avisa que está
    aguardando, aceita cancelamento e volta a atender se o cliente pedir.
    """
    if plan.has(Action.CANCEL_ORDER):
        return _cancel(session)

    # Qualquer operação de pedido significa "quero seguir por aqui mesmo".
    quer_o_bot = any(
        action
        in {
            Action.ADD_ITEM,
            Action.UPDATE_ITEM,
            Action.REPLACE_ITEM,
            Action.REMOVE_ITEM,
            Action.UPDATE_QUANTITY,
            Action.DUPLICATE_ITEM,
            Action.CLOSE_ORDER,
            Action.CONFIRM_ORDER,
            Action.SHOW_MENU,
        }
        for action in plan.actions
    )
    if quer_o_bot:
        _resume_from_human(session)
        return None  # o turno segue normalmente; quem chama põe o aviso

    # Avisa que está esperando — mas uma vez a cada tanto, não a cada mensagem.
    if session.slots.get("handoff_avisado"):
        return []
    session.slots["handoff_avisado"] = True
    return [r.still_waiting_human()]


#: Respostas mornas. A lista é curta e existe por um motivo só: impedir que
#: uma quase-confirmação vire cobrança. Não é o cliente que precisa falar
#: assim — é o sistema que se recusa a cobrar sem um sim claro.
_MORNAS = (
    "pode ser",
    "acho que sim",
    "acho que e isso",
    "talvez",
    "tanto faz",
    "sei la",
    "vamo ver",
    "deve ser",
)


def _hedged(text: str) -> bool:
    limpo = normalize(text).strip(" .!?")
    return any(limpo == m or limpo.startswith(m + " ") for m in _MORNAS)


def _cancel(session: ConversationSession) -> list[str]:
    if session.state in CANCELLABLE_STATES or session.state is S.ATENDIMENTO_HUMANO:
        if session.state is S.ATENDIMENTO_HUMANO:
            session.handoff = False
        _go(session, S.CANCELADO)
    session.slots = {}
    session.cart.items.clear()
    session.active_order_id = None
    session.fail_count = 0
    return [r.cancelled()]


# ---------------------------------------------------------------------------
# Situação (o que a IA recebe junto com a mensagem)
# ---------------------------------------------------------------------------

def describe_situation(deps: AgentDeps, session: ConversationSession) -> str:
    """Retrato do pedido agora, em português, para o modelo.

    É isto que deixa "esse mesmo", "o segundo", "pode ser" e "1 e 3" serem
    resolvidos sem obrigar o cliente a repetir nomes.
    """
    linhas: list[str] = []

    draft = _draft(session)
    if draft is not None:
        product, group = _first_open_group(deps, draft)
        escolhidos = [f["name"] for f in draft["flavors"]]
        if product is not None and group is not None:
            faltam = max(group.min_choices - len(escolhidos), 0)
            linhas.append(
                f"Montando agora: {draft['quantity']}x {product.name}. "
                + (f"Sabores já escolhidos: {', '.join(escolhidos)}. " if escolhidos
                   else "Nenhum sabor escolhido ainda. ")
                + f"Faltam {faltam} de {group.min_choices}."
            )
            disponiveis = [
                c.name for c in group.available_complements if c.name not in escolhidos
            ]
            linhas.append("Sabores que ainda cabem neste pote: " + ", ".join(disponiveis))
        elif product is not None:
            linhas.append(f"Montando agora: {draft['quantity']}x {product.name} (completo).")

    if not session.cart.is_empty:
        itens = []
        for i, item in enumerate(session.cart.items, start=1):
            sabores = f" ({', '.join(c.name for c in item.complements)})" if item.complements else ""
            itens.append(f"{i}. {item.quantity}x {item.product_name}{sabores}")
        linhas.append("No pedido:\n" + "\n".join(itens))
    elif draft is None:
        linhas.append("Pedido vazio — o cliente ainda não escolheu nada.")

    kind = fulfillment_of(session)
    if kind is not None:
        linhas.append(f"Forma de entrega já definida: {kind.value}.")

    endereco = address_of(session)
    if endereco:
        faltando = missing_address_fields(endereco)
        linhas.append(
            f"Endereço incompleto, falta: {', '.join(faltando)}."
            if faltando
            else "Endereço completo."
        )

    if session.slots.get(AWAITING_CONFIRM):
        linhas.append(
            "ATENÇÃO: acabamos de mostrar o RESUMO FINAL com o total e estamos "
            "esperando o cliente confirmar. Um sim claro aqui é confirm_order."
        )
    elif session.slots.get(CLOSING):
        linhas.append("O cliente já disse que quer fechar o pedido.")

    ultima = session.slots.get(LAST_OFFER)
    if ultima:
        linhas.append(
            "Última lista numerada mostrada a ele: "
            + "; ".join(f"{i}. {nome}" for i, nome in enumerate(ultima, start=1))
        )

    return "\n".join(linhas) or "Conversa começando, nada pedido ainda."


# ---------------------------------------------------------------------------
# O turno
# ---------------------------------------------------------------------------

async def run(
    deps: AgentDeps,
    session: ConversationSession,
    plan: AgentPlan,
    text: str,
) -> list[str]:
    """Aplica o plano da IA e devolve o que o bot vai falar."""
    voltou_do_humano = False
    if session.handoff or session.state is S.ATENDIMENTO_HUMANO:
        if human_on_the_line(session):
            resposta = _handoff_turn(session, plan)
            if resposta is not None:
                return resposta
            voltou_do_humano = True
        else:
            logger.info("handoff sem resposta humana; o bot reassume a conversa")
            _resume_from_human(session)

    if session.state in {S.CONCLUIDO, S.CANCELADO}:
        # Mensagem nova depois de um pedido fechado abre um ciclo limpo.
        _go(session, S.CONVERSANDO)
        session.slots = {k: v for k, v in session.slots.items() if k == "customer_name"}
        session.cart.items.clear()
        session.active_order_id = None

    if plan.customer_name and "customer_name" not in session.slots:
        session.slots["customer_name"] = plan.customer_name

    primeira_vez = not session.slots.get("ja_falamos")
    session.slots["ja_falamos"] = True

    turn = _Turn()

    # A confirmação é a única operação que mexe em dinheiro: ela sai da fila e
    # só vale se houver um resumo na tela esperando resposta.
    if plan.has(Action.CONFIRM_ORDER) and session.slots.get(AWAITING_CONFIRM):
        if _hedged(text):
            # "pode ser", "acho que sim": o modelo classifica isso como
            # confirmação, mas não é um sim. Cobrança não se faz com
            # quase-certeza — o cliente responde uma vez mais, e aí sim.
            return [r.confirm_once_more()]
        session.slots.pop(AWAITING_CONFIRM, None)
        return await place_order(deps, session)

    for op in plan.operations:
        await _apply(deps, session, op, turn)
        if turn.finished is not None:
            return turn.finished

    replies = await _next_step(deps, session, plan, turn)
    if voltou_do_humano and replies:
        replies = [r.back_from_human()] + replies
    if primeira_vez and replies:
        # Bom dia uma vez só, no começo da conversa — como gente faz.
        replies = [r.greeting()] + replies
    return [reply for reply in replies if reply]


async def _next_step(
    deps: AgentDeps, session: ConversationSession, plan: AgentPlan, turn: _Turn
) -> list[str]:
    """Depois de aplicar tudo: o que o bot fala agora.

    Uma pergunta por turno, sempre a do ponto em que o pedido está. É aqui que
    "pergunta não derruba o fluxo" acontece: se o turno só respondeu algo, o
    bot devolve o cliente exatamente para onde ele estava.
    """
    # 1. O turno só respondeu algo (pergunta, cardápio, carrinho): devolve o
    #    cliente para onde ele estava, com a retomada CURTA — repetir a lista
    #    inteira de sabores a cada dúvida é o que cansava o WhatsApp.
    if turn.answered and not turn.changed:
        session.fail_count = 0
        # Se a própria resposta já terminou em pergunta, não emendar outra:
        # duas perguntas seguidas soam como formulário.
        if turn.notes and turn.notes[-1].rstrip().endswith("?"):
            return turn.notes
        retomada = _resume_prompt(deps, session)
        return turn.notes + ([retomada] if retomada else [])

    # 2. Rascunho incompleto: falta escolher sabor.
    draft = _draft(session)
    if draft is not None:
        product, group = _first_open_group(deps, draft)
        if product is not None and group is not None:
            session.fail_count = 0
            session.slots[LAST_OFFER] = [
                c.name for c in group.available_complements
            ]
            escolhidos = [f["name"] for f in draft["flavors"]]
            return turn.notes + [r.ask_flavors(product, group, escolhidos)]
        item = _commit_draft(deps, session)
        if item is not None:
            turn.say(r.item_added(item))

    # 3. Fechando o pedido.
    if session.slots.get(CLOSING) and not session.cart.is_empty:
        session.fail_count = 0
        return turn.notes + await _checkout_step(deps, session)

    # 4. Mexeu no pedido: confirma e pergunta se quer mais.
    if turn.changed:
        session.fail_count = 0
        session.slots.pop(AWAITING_CONFIRM, None)
        if session.cart.is_empty:
            return turn.notes + [_menu(deps, session)]
        return turn.notes + [r.ask_more_or_close(session.cart)]

    # 5. Cumprimento, agradecimento, conversa fiada: abre o atendimento em vez
    #    de dizer "não entendi" a quem só disse oi.
    if plan.has(Action.NO_ACTION) and _draft(session) is None and session.cart.is_empty:
        session.fail_count = 0
        return turn.notes + [_menu(deps, session)]

    # 6. Nada aconteceu mesmo: reparo progressivo, sem cardápio na cara dele.
    return _fallback(deps, session, plan)


async def _checkout_step(deps: AgentDeps, session: ConversationSession) -> list[str]:
    """Entrega ou retirada → endereço → resumo. Nada disso cobra nada."""
    kind = fulfillment_of(session)
    if kind is None:
        return [r.ask_fulfillment()]

    if kind is FulfillmentType.ENTREGA:
        endereco = address_of(session)
        if not endereco and deps.saved_address is not None:
            salvo = await deps.saved_address()
            if salvo and not missing_address_fields(salvo):
                session.slots["address"] = salvo
        faltando = missing_address_fields(address_of(session))
        if faltando:
            return [r.ask_address(faltando)]

    _go(session, S.CONFIRMANDO_PEDIDO)
    session.slots[AWAITING_CONFIRM] = True
    return [final_summary(deps, session)]


def _resume_prompt(deps: AgentDeps, session: ConversationSession) -> str | None:
    """A pergunta do ponto em que o pedido está, para retomar depois de uma dúvida."""
    draft = _draft(session)
    if draft is not None:
        product, group = _first_open_group(deps, draft)
        if product is not None and group is not None:
            return r.resume_flavors(product, group, [f["name"] for f in draft["flavors"]])
    if session.slots.get(AWAITING_CONFIRM):
        return r.ask_confirm_short()
    if session.slots.get(CLOSING) and fulfillment_of(session) is None:
        return r.ask_fulfillment()
    if not session.cart.is_empty:
        return r.ask_more_or_close(session.cart)
    return r.ask_what_they_want()


def _fallback(
    deps: AgentDeps, session: ConversationSession, plan: AgentPlan
) -> list[str]:
    """Reparo progressivo: reformula, depois oferece gente — nunca cala.

    Antes, a terceira mensagem não entendida jogava o cliente no atendimento
    humano (e no silêncio). Três perguntas banais bastavam.
    """
    session.fail_count += 1
    retomada = _resume_prompt(deps, session)

    if session.fail_count == 1:
        return [r.didnt_get_it(), *( [retomada] if retomada else [] )]
    if session.fail_count == 2:
        return [r.didnt_get_it_again(), *( [retomada] if retomada else [] )]

    session.fail_count = 0
    return [r.offer_human(), *( [retomada] if retomada else [] )]
