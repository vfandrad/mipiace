"""O que cada operação faz com o pedido.

A IA diz *qual* operação o cliente quer; este módulo aplica, e é ele que decide
se aquilo é possível. Nenhuma linha daqui conduz a conversa — quem faz isso é
`machine.py`, que chama `apply()` uma vez por operação e depois decide o que o
bot fala. A divisão é essa:

    machine.py    conduz o turno (o que perguntar agora, fallback, handoff)
    operations.py mexe no pedido (adicionar, trocar, remover, endereço)

O que vale para tudo aqui dentro:

- **Editar não é adicionar.** "troca chocolate por fior di latte", "remove o
  item 1", "na verdade só um" mexem no item que já existe. Criar item novo aí
  faz o cliente pagar duas vezes — foi o pior defeito que o agente já teve.
- **O catálogo é quem decide.** A IA propõe um nome; `find_product` e
  `find_flavors` dizem se existe, se está disponível e se é ambíguo.
- **Um pedido é uma lista só.** O item que ainda está sendo montado (faltam
  sabores) fica no carrinho como qualquer outro, na mesma numeração que o
  cliente vê. Antes ele morava fora, num "rascunho": o cliente enxergava dois
  itens e a IA recebia um numerado e outro não, então "tira o médio" chegava
  aqui como `item_index=1` — e o executor apagava o pote grande. Um item, um
  número, para todo mundo.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import get_close_matches
from typing import Any
from uuid import UUID

from app.agent import faq
from app.agent import renderer as r
from app.agent.checkout import (
    AgentDeps,
    address_of,
    fulfillment_of,
    missing_address_fields,
    set_fulfillment,
)
from app.agent.plan import Action, Operation
from app.agent.resolver import MatchStatus, resolve_product
from app.agent.session import ConversationSession
from app.agent.states import CANCELLABLE_STATES, can_transition
from app.agent.states import advance as _go
from app.core.config import get_settings
from app.domain.cart import CartComplement, CartItem
from app.domain.catalog import CatalogGroup, CatalogProduct, normalize
from app.domain.enums import ConversationState as S
from app.domain.enums import FulfillmentType

logger = logging.getLogger(__name__)

#: Slots usados pelo executor.
CLOSING = "closing"                    # o cliente já disse que quer fechar
AWAITING_CONFIRM = "awaiting_confirm"  # resumo final na tela, esperando "sim"
LAST_OFFER = "last_offer"              # a última lista numerada que mostramos
LEGACY_DRAFT = "draft"                 # conversas antigas (ver `adopt_legacy_draft`)


@dataclass
class Turn:
    """O que aconteceu neste turno, para compor UMA resposta no fim.

    Sem isto o bot responde uma mensagem por operação e vira metralhadora:
    "Tirei o X." / "Adicionei o Y." / "Anotei entrega." / "Qual o endereço?".
    """

    notes: list[str] = field(default_factory=list)   # o que o bot confirma/responde
    changed: bool = False                            # mexeu no pedido?
    answered: bool = False                           # respondeu pergunta?
    finished: list[str] | None = None                # resposta final (Pix, cancelamento)

    def say(self, *texts: str) -> None:
        """Acrescenta falas, sem repetir a mesma no mesmo turno.

        O modelo às vezes reparte uma frase em várias operações (um
        `update_address` por campo do endereço), e o cliente recebia
        "Endereço anotado" três vezes seguidas.
        """
        for texto in texts:
            if texto and texto not in self.notes:
                self.notes.append(texto)


# ---------------------------------------------------------------------------
# Itens do pedido (completos e em montagem, na mesma lista)
# ---------------------------------------------------------------------------

def product_of(deps: AgentDeps, item: CartItem) -> CatalogProduct | None:
    return deps.catalog.product_by_id(item.product_id)


def open_group(deps: AgentDeps, item: CartItem) -> CatalogGroup | None:
    """O grupo obrigatório deste item que ainda não fechou, se houver."""
    product = product_of(deps, item)
    if product is None:
        return None
    for group in product.required_groups:
        escolhidos = [c for c in item.complements if c.group_id == group.id]
        if len(escolhidos) < group.min_choices:
            return group
    return None


def _is_complete(deps: AgentDeps, item: CartItem) -> bool:
    return open_group(deps, item) is None


def pending_index(deps: AgentDeps, session: ConversationSession) -> int | None:
    """O primeiro item que ainda está sendo montado."""
    for i, item in enumerate(session.cart.items):
        if not _is_complete(deps, item):
            return i
    return None


def _pending(deps: AgentDeps, session: ConversationSession) -> CartItem | None:
    i = pending_index(deps, session)
    return session.cart.items[i] if i is not None else None


def _new_item(
    session: ConversationSession, product: CatalogProduct, quantity: int = 1
) -> CartItem:
    item = CartItem(
        product_id=product.id,
        product_name=product.name,
        unit_base_price=product.base_price,
        quantity=max(1, quantity),
    )
    session.cart.items.append(item)
    return item


def adopt_legacy_draft(deps: AgentDeps, session: ConversationSession) -> None:
    """Conversa aberta na versão anterior: traz o rascunho para o carrinho.

    Sem isto, quem estava no meio de um pedido quando o sistema subiu perderia
    o item em montagem — o pior momento possível para perder alguma coisa.
    """
    draft = session.slots.pop(LEGACY_DRAFT, None)
    if not isinstance(draft, dict):
        return
    product = deps.catalog.product_by_id(UUID(draft["product_id"]))
    if product is None:
        return
    item = _new_item(session, product, int(draft.get("quantity", 1)))
    for f in draft.get("flavors", []):
        try:
            item.complements.append(
                CartComplement(
                    id=UUID(f["id"]),
                    group_id=UUID(f["group_id"]),
                    name=f["name"],
                    extra_price=Decimal(f["extra_price"]),
                )
            )
        except (KeyError, ValueError):  # rascunho estranho: melhor perder o sabor
            continue


# ---------------------------------------------------------------------------
# Alvo (qual item a operação atinge)
# ---------------------------------------------------------------------------

def _target(
    deps: AgentDeps, session: ConversationSession, op: Operation
) -> int | None:
    """Índice do item que a operação atinge, ou None quando não dá para saber.

    A ordem importa e cada degrau tem uma história:

    1. o número que a IA mandou, que é o mesmo que o cliente viu na tela;
    2. o produto que ele nomeou, se estiver no pedido;
    3. o item em montagem — é dele que o cliente está falando quando não diz
       qual;
    4. o único item do pedido.

    O degrau que não existe é o perigoso: quando o cliente **nomeia** um
    produto que não está no pedido, não se chuta o item que está. Era assim
    que "tira o médio" removia o pote grande.
    """
    itens = session.cart.items
    if not itens:
        return None

    if op.item_index is not None:
        if 1 <= op.item_index <= len(itens):
            return op.item_index - 1
        # Índice fora da lista com um item só: ele quis dizer esse.
        return 0 if len(itens) == 1 else None

    if op.product_name:
        alvo = normalize(op.product_name)
        achados = [i for i, item in enumerate(itens) if normalize(item.product_name) == alvo]
        if achados:
            # Dois iguais no pedido: mexe no último, como gente espera.
            return achados[-1]
        if deps.catalog.product_by_name(op.product_name) is not None:
            return None

    pendente = pending_index(deps, session)
    if pendente is not None:
        return pendente
    if len(itens) == 1:
        return 0
    return None


def _group_of(deps: AgentDeps, item: CartItem) -> CatalogGroup | None:
    """O grupo de sabores do item — o aberto, ou o primeiro que ele tem."""
    aberto = open_group(deps, item)
    if aberto is not None:
        return aberto
    product = product_of(deps, item)
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
    item: CartItem,
    group: CatalogGroup,
    *,
    add: Sequence[Any],
    remove_names: Sequence[str],
    turn: Turn,
) -> None:
    """Tira e põe sabores no MESMO item, respeitando o máximo e sem repetir."""
    atuais = item.complements
    repetidos: list[str] = []
    mexeu = False

    # O modelo às vezes devolve em remove_flavors um sabor que o cliente
    # acabou de PEDIR ("no médio bota coco e banoffe" com o banoffe já lá).
    # Tirar e pôr o mesmo sabor no mesmo turno nunca é o que ele quis.
    pedidos = {normalize(c.name) for c in add}
    remove_names = [n for n in remove_names if normalize(n) not in pedidos]

    # Remoções primeiro: é o que faz "troca X por Y" caber no mesmo item.
    for nome in remove_names:
        alvo = normalize(nome)
        for atual in list(atuais):
            if normalize(atual.name) == alvo:
                atuais.remove(atual)
                turn.say(r.flavor_removed(atual.name))
                turn.changed = True
                mexeu = True
                break

    for escolha in add:
        if len(atuais) >= group.max_choices:
            turn.say(r.group_full(group))
            break
        if any(c.id == escolha.id for c in atuais):
            # Sabor não se repete no mesmo pote. O modelo costuma REPETIR os
            # já escolhidos junto com o novo ("troca morango por chocolate"
            # volta com Pistache também): aí a repetição é só ruído e some.
            # Só vira aviso quando foi o cliente que pediu duas vezes.
            repetidos.append(escolha.name)
            continue
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


def _flavors_into(
    deps: AgentDeps, item: CartItem, op: Operation, turn: Turn
) -> None:
    """Aplica os sabores da operação no item, no grupo certo."""
    if not (op.add_flavors or op.remove_flavors):
        return
    group = _group_of(deps, item)
    if group is None:
        if op.add_flavors:
            turn.say(r.item_has_no_flavors(item.product_name))
            turn.answered = True
        return
    achados, problemas = _find_flavors(group, op.add_flavors)
    turn.say(*problemas)
    _apply_flavors(item, group, add=achados, remove_names=op.remove_flavors, turn=turn)


# ---------------------------------------------------------------------------
# As operações
# ---------------------------------------------------------------------------

async def apply(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    turn: Turn,
    mensagem: str = "",
) -> None:
    """Aplica UMA operação. Nada aqui responde ao cliente diretamente.

    `mensagem` é o texto cru do cliente. Só o endereço o usa, e por um motivo
    que vale a passagem do parâmetro: é o único dado do pedido que não tem
    catálogo contra o qual ser conferido (ver `_merge_address`).
    """
    action = op.action

    # O modelo costuma pendurar a forma de entrega e o endereço na MESMA
    # operação do item ("quero um pote G, vou retirar"). Lidos só na operação
    # dedicada, eles se perdiam e o bot perguntava de novo lá na frente.
    if op.fulfillment and action is not Action.SET_FULFILLMENT:
        _set_fulfillment(session, op.fulfillment, turn)
    if op.address is not None and action is not Action.UPDATE_ADDRESS:
        _merge_address(session, op.address, turn, mensagem)

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
        _merge_address(session, op.address, turn, mensagem)

    elif action is Action.SHOW_MENU:
        turn.say(menu(deps, session))
        turn.answered = True

    elif action is Action.SHOW_CART:
        turn.say(
            r.cart_summary(session.cart, pending=pending_index(deps, session))
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
        turn.finished = cancel(session)

    elif action is Action.REQUEST_HUMAN:
        turn.finished = to_human(session)

    elif action is Action.ASK_CLARIFICATION:
        turn.say(op.clarification or r.ask_clarification())
        turn.answered = True

    # CONFIRM_ORDER e NO_ACTION são tratados em `run`: um mexe em dinheiro, o
    # outro é a ausência de operação.


def _set_fulfillment(session: ConversationSession, escolha: str | None, turn: Turn) -> None:
    """Entrega ou retirada — e o bot DIZ que anotou.

    Anotar em silêncio fazia o cliente repetir: ele dizia "quero entrega", via
    o resumo do carrinho de volta e achava que tinha sido ignorado.
    """
    if escolha == "retirada":
        kind = FulfillmentType.RETIRADA
    elif escolha == "entrega":
        kind = FulfillmentType.ENTREGA
    else:
        return
    mudou = fulfillment_of(session) is not kind
    set_fulfillment(session, kind)
    if mudou:
        turn.say(r.fulfillment_set(kind))
    turn.changed = True


def _disse_isso(valor: str, mensagem: str) -> bool:
    """O cliente realmente escreveu este pedaço de endereço?

    Produto e sabor têm o catálogo para dizer se existem. **Endereço não tem** —
    é texto livre, e por isso é o único campo em que a IA consegue inventar um
    dado sem nada a contradizê-la. E inventou: respondendo "sim" à pergunta
    "qual o bairro?", o modelo preencheu "Jardim América", um bairro que o
    cliente nunca digitou. A entrega iria para o lugar errado.

    A conferência é frouxa de propósito — basta uma palavra do valor aparecer
    na mensagem, e palavra parecida conta (o cliente escreve "flres", o modelo
    normaliza para "Flores"). O que ela barra é o caso que importa: um valor
    que não tem relação nenhuma com o que foi dito.
    """
    limpo = normalize(valor).strip()
    mensagem_limpa = normalize(mensagem)
    if not limpo or not mensagem_limpa:
        return False
    # O valor inteiro aparecendo no texto já resolve — e cobre o nome curto
    # ("Rua X"), que não sobreviveria a uma comparação por palavra.
    if limpo in mensagem_limpa:
        return True
    palavras_msg = [p for p in re.split(r"[^a-z0-9]+", mensagem_limpa) if p]
    palavras_valor = [p for p in limpo.split() if len(p) >= 2]
    if not palavras_valor or not palavras_msg:
        return False
    return any(
        palavra in palavras_msg or get_close_matches(palavra, palavras_msg, n=1, cutoff=0.75)
        for palavra in palavras_valor
    )


def _merge_address(
    session: ConversationSession, address: Any, turn: Turn, mensagem: str = ""
) -> None:
    """Endereço é objeto: o cliente completa em qualquer ordem, em qualquer turno."""
    if address is None:
        return
    endereco = address_of(session)
    for campo, valor in address.model_dump().items():
        if not valor:
            continue
        if mensagem and not _disse_isso(str(valor), mensagem):
            logger.info(
                "endereço: campo %s=%r descartado, não está na mensagem do cliente",
                campo,
                valor,
            )
            continue
        endereco[campo] = valor
    session.slots["address"] = endereco
    ja_era_entrega = fulfillment_of(session) is FulfillmentType.ENTREGA
    set_fulfillment(session, FulfillmentType.ENTREGA)
    if not missing_address_fields(endereco):
        turn.say(r.address_saved(endereco, novo_para_entrega=not ja_era_entrega))
    turn.changed = True


def _op_add_item(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: Turn
) -> None:
    """Item NOVO no pedido — com uma exceção, que evita item fantasma.

    Se já existe um item EM MONTAGEM do mesmo produto, a operação cai nele. O
    modelo manda `add_item` com frequência para o que é resposta à pergunta
    dos sabores ("pistache e morango" depois de "fechado, G - 500ml!"), e sem
    isto cada resposta dessas criava outro pote vazio: o pedido enchia de
    itens que ninguém pediu e nenhum deles ficava completo.

    Quem quer mesmo um segundo pote igual diz "outro igual" (duplicate_item)
    ou dá a quantidade — e o pote só vira "de verdade" depois de fechado.
    """
    product, problema = _find_product(deps, op)
    pendente = _pending(deps, session)

    if product is None:
        # Sem produto identificado, mas com sabores: é resposta à pergunta do
        # item que está aberto.
        if pendente is not None and (op.add_flavors or op.remove_flavors):
            _flavors_into(deps, pendente, op, turn)
            if _is_complete(deps, pendente):
                turn.say(r.item_added(pendente))
            return
        if problema:
            turn.say(problema)
            turn.answered = True
        return

    if pendente is not None and pendente.product_id == product.id:
        if op.quantity:
            pendente.quantity = max(1, op.quantity)
            turn.changed = True
        _flavors_into(deps, pendente, op, turn)
        if _is_complete(deps, pendente):
            turn.say(r.item_added(pendente))
        return

    item = _new_item(session, product, op.quantity or 1)
    turn.changed = True
    _flavors_into(deps, item, op, turn)
    if _is_complete(deps, item):
        turn.say(r.item_added(item))


def _op_update_item(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: Turn
) -> None:
    """Mexe num item que já existe — nunca cria um novo."""
    # Trocar o produto (replace) tem prioridade sobre mexer em sabor.
    quer_trocar_produto = op.action is Action.REPLACE_ITEM or (
        op.product_name and not op.add_flavors and not op.remove_flavors
    )
    if quer_trocar_produto:
        product, problema = _find_product(deps, op)
        if product is None:
            if problema:
                turn.say(problema)
                turn.answered = True
            return
        # Aqui `product_name` é o produto NOVO, não o alvo: procurar o alvo
        # por ele acharia "o Pote 240ml que ainda não existe no pedido".
        index = _target(
            deps, session, Operation(action=op.action, item_index=op.item_index)
        )
        if index is None:
            if session.cart.is_empty:
                # "na verdade quero o médio" sem nada no pedido: é um item novo.
                _op_add_item(deps, session, op, turn)
                return
            turn.say(r.ask_which_item(session.cart))
            turn.answered = True
            return
        antigo = session.cart.items[index]
        if antigo.product_id == product.id:
            _flavors_into(deps, antigo, op, turn)
            return
        _replace_product(deps, session, index, product, turn)
        return

    index = _target(deps, session, op)
    if index is None:
        turn.say(r.ask_which_item(session.cart))
        turn.answered = True
        return

    item = session.cart.items[index]
    estava_completo = _is_complete(deps, item)
    _flavors_into(deps, item, op, turn)
    if turn.changed and estava_completo and _is_complete(deps, item):
        turn.say(r.item_updated(item))


def _replace_product(
    deps: AgentDeps,
    session: ConversationSession,
    index: int,
    product: CatalogProduct,
    turn: Turn,
) -> None:
    """Troca o produto do item mantendo os sabores que ainda existem nele."""
    antigo = session.cart.items[index]
    novo = CartItem(
        product_id=product.id,
        product_name=product.name,
        unit_base_price=product.base_price,
        quantity=antigo.quantity,
    )
    session.cart.items[index] = novo
    group = _group_of(deps, novo)
    if group is not None and antigo.complements:
        achados, _ = _find_flavors(group, [c.name for c in antigo.complements])
        _apply_flavors(novo, group, add=achados, remove_names=[], turn=turn)
    turn.say(r.product_switched(antigo.product_name, product.name))
    turn.changed = True


def _op_remove_item(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: Turn
) -> None:
    if session.cart.is_empty:
        turn.say(r.cart_empty())
        turn.answered = True
        return

    index = _target(deps, session, op)

    # "tira o pistache" é tirar o sabor, não o item.
    #
    # Esta guarda é a mais importante do módulo: enquanto a operação só citar
    # SABORES — sem número de item e sem nome de produto —, ela não pode
    # apagar item nenhum. O modelo manda remove_item com remove_flavors com
    # alguma frequência (dizer "pistache, morango e pistache" já bastou), e
    # sem isto o cliente perde o pote inteiro por ter repetido um sabor.
    so_fala_de_sabor = bool(op.remove_flavors) and not op.product_name and op.item_index is None
    if op.remove_flavors and index is not None:
        item = session.cart.items[index]
        group = _group_of(deps, item)
        tem_o_sabor = any(
            normalize(c.name) in {normalize(n) for n in op.remove_flavors}
            for c in item.complements
        )
        if group is not None and (tem_o_sabor or so_fala_de_sabor):
            _apply_flavors(
                item, group, add=[], remove_names=op.remove_flavors, turn=turn
            )
            return
    if so_fala_de_sabor:
        return  # sabor que não está em lugar nenhum: não se apaga o item por isso

    if index is None:
        turn.say(r.ask_which_item(session.cart))
        turn.answered = True
        return

    item = session.cart.items[index]

    # "tira UMA casquinha" com 3 no pedido tira uma, não a linha inteira. O
    # executor ignorava `quantity` e apagava as três — o cliente perdia R$ 18
    # e o bot ainda dizia "Tirei o Casquinha", no singular, escondendo o
    # tamanho do estrago.
    if op.quantity and 0 < op.quantity < item.quantity:
        item.quantity -= op.quantity
        turn.say(r.quantity_updated(item))
        turn.changed = True
        return

    removido = session.cart.items.pop(index)
    turn.say(r.item_removed(removido.product_name))
    turn.changed = True


def _op_quantity(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: Turn
) -> None:
    if op.quantity is None:
        return

    index = _target(deps, session, op)
    if index is None:
        # "quero 2 cascões" com o cascão fora do pedido é adicionar, não
        # mudar a quantidade do que já está lá — senão o cliente leva dois
        # potes de R$ 50 achando que pediu dois casquinhos.
        if op.product_name and deps.catalog.product_by_name(op.product_name):
            _op_add_item(deps, session, op, turn)
            return
        turn.say(r.ask_which_item(session.cart))
        turn.answered = True
        return

    item = session.cart.items[index]
    item.quantity = max(1, op.quantity)
    turn.say(r.quantity_updated(item))
    turn.changed = True


def _op_duplicate(
    deps: AgentDeps, session: ConversationSession, op: Operation, turn: Turn
) -> None:
    # "põe também 2 cascões" chega do modelo como duplicate_item com o nome de
    # OUTRO produto. Duplicar aí repetiria o pote de R$ 50 que já estava no
    # carrinho. Quando o nome é de outro item, isto é adicionar, não duplicar.
    if op.product_name:
        alvo = deps.catalog.product_by_name(op.product_name)
        index = _target(deps, session, Operation(action=op.action, item_index=op.item_index))
        atual = session.cart.items[index] if index is not None else None
        if alvo is not None and (atual is None or alvo.id != atual.product_id):
            _op_add_item(deps, session, op, turn)
            return

    if session.cart.is_empty:
        turn.say(r.cart_empty())
        turn.answered = True
        return

    index = _target(deps, session, op)
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

def menu(deps: AgentDeps, session: ConversationSession) -> str:
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
    return r.total_reply(
        session.cart,
        taxa,
        is_pickup=kind is FulfillmentType.RETIRADA,
        pending=pending_index(deps, session),
    )


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

def to_human(session: ConversationSession) -> list[str]:
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


def resume_from_human(session: ConversationSession) -> None:
    session.handoff = False
    session.slots.pop("handoff_since", None)
    session.slots.pop("handoff_avisado", None)
    session.fail_count = 0
    if session.state is S.ATENDIMENTO_HUMANO:
        _go(session, S.CONVERSANDO)


#: O que o cliente diz quando quer o bot de volta. É uma lista curta e ela não
#: obriga ninguém a falar assim: qualquer operação de pedido também traz a
#: conversa de volta. Ela existe para "deixa pra lá, continua você" — que não



def cancel(session: ConversationSession) -> list[str]:
    if session.state in CANCELLABLE_STATES or session.state is S.ATENDIMENTO_HUMANO:
        if session.state is S.ATENDIMENTO_HUMANO:
            session.handoff = False
        _go(session, S.CANCELADO)
    session.slots = {}
    session.cart.items.clear()
    session.active_order_id = None
    session.fail_count = 0
    return [r.cancelled()]

