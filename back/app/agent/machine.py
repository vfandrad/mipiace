"""O turno da conversa: o que o bot fala depois de aplicar o que a IA entendeu.

A divisão de trabalho, que é o ponto do desenho:

    mensagem → LLM → operações → operations.py → estado do pedido
                                       ↓
                            ESTE MÓDULO decide a resposta
                                       ↓
                                   WhatsApp

A IA tem liberdade para interpretar linguagem natural e dizer *qual operação*
o cliente quer. Ela não tem autoridade para inventar produto, preço, taxa ou
disponibilidade, nem para cobrar: cada operação é validada em `operations.py`
contra o catálogo real, e só uma confirmação explícita sobre um resumo que o
cliente viu gera Pix.

O que mora aqui, e só aqui:

- **Uma pergunta por turno**, sempre a do ponto em que o pedido está.
- **Pergunta não derruba o fluxo.** Respondida a dúvida, o cliente volta
  exatamente para onde estava (`_resume_prompt`).
- **A etapa do diálogo não é estado.** Ela está nos dados do pedido: tem item
  incompleto? falta endereço? (ver `states.py`).
- **Atendimento humano não vira silêncio.** Em handoff o bot para de conduzir
  o pedido, mas continua ouvindo (`_handoff_turn`).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.agent import renderer as r
from app.agent.checkout import (
    AgentDeps,
    address_of,
    final_summary,
    fulfillment_of,
    missing_address_fields,
    place_order,
)
from app.agent.operations import (
    AWAITING_CONFIRM,
    CLOSING,
    LAST_OFFER,
    Turn,
    adopt_legacy_draft,
    apply,
    cancel,
    human_on_the_line,
    menu,
    open_group,
    pending_index,
    pending_order_status,
    product_of,
    resume_from_human,
)
from app.agent.plan import Action, AgentPlan
from app.agent.session import ConversationSession
from app.agent.states import advance as _go
from app.domain.catalog import normalize
from app.domain.enums import ConversationState as S
from app.domain.enums import FulfillmentType

logger = logging.getLogger(__name__)



#: O que o cliente diz quando quer o bot de volta. É uma lista curta e ela não
#: obriga ninguém a falar assim: qualquer operação de pedido também traz a
#: conversa de volta. Ela existe para "deixa pra lá, continua você" — que não
#: é operação nenhuma e, sem isto, virava outra mensagem de espera.
_VOLTAR_PRO_BOT = (
    "deixa pra la",
    "deixa quieto",
    "continua voce",
    "continua vc",
    "pode continuar",
    "segue voce",
    "segue vc",
    "nao precisa",
    "esquece",
    "pode ser com voce",
    "pode ser com vc",
    "com voce mesmo",
    "com vc mesmo",
    "voce mesmo",
    "vc mesmo",
)


def _quer_o_bot_de_volta(text: str) -> bool:
    limpo = normalize(text)
    return any(termo in limpo for termo in _VOLTAR_PRO_BOT)


def _handoff_turn(
    session: ConversationSession, plan: AgentPlan, text: str
) -> list[str] | None:
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
        return cancel(session)

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
            Action.SET_FULFILLMENT,
            Action.UPDATE_ADDRESS,
            Action.CLOSE_ORDER,
            Action.CONFIRM_ORDER,
            Action.SHOW_MENU,
            Action.SHOW_CART,
            Action.SHOW_TOTAL,
        }
        for action in plan.actions
    )
    if quer_o_bot or _quer_o_bot_de_volta(text):
        resume_from_human(session)
        return None  # o turno segue normalmente; quem chama põe o aviso

    # Avisa que está esperando — mas uma vez a cada tanto, não a cada mensagem.
    #
    # O "a cada tanto" era só promessa: o slot `handoff_avisado` era gravado uma
    # vez e nunca mais limpo, então a partir da TERCEIRA mensagem o turno
    # devolvia lista vazia para sempre. Três clientes simulados bateram nisso —
    # "alooo? tem alguém aí?" ficou sem resposta nenhuma. Era exatamente o que
    # esta função existe para impedir.
    #
    # Agora o silêncio é limitado no tempo: o aviso longo sai de novo depois de
    # `_MINUTOS_ENTRE_AVISOS`, e no intervalo sai um reconhecimento curto. O
    # cliente nunca fala com o vazio.
    ultimo = session.slots.get("handoff_avisado_em")
    agora = datetime.now(timezone.utc)
    if isinstance(ultimo, str):
        try:
            desde = (agora - datetime.fromisoformat(ultimo)).total_seconds() / 60
        except ValueError:
            desde = float("inf")
    else:
        desde = float("inf")

    if desde >= _MINUTOS_ENTRE_AVISOS:
        session.slots["handoff_avisado_em"] = agora.isoformat()
        return [r.still_waiting_human()]
    return [r.still_waiting_human_short()]


#: Operações que mexem no pedido. Enquanto houver Pix pendente elas ficam
#: bloqueadas — cancelar, perguntar e pedir gente seguem valendo.
_MEXEM_NO_PEDIDO = frozenset(
    {
        Action.ADD_ITEM,
        Action.UPDATE_ITEM,
        Action.REPLACE_ITEM,
        Action.REMOVE_ITEM,
        Action.UPDATE_QUANTITY,
        Action.DUPLICATE_ITEM,
        Action.CLOSE_ORDER,
        Action.CONFIRM_ORDER,
    }
)


#: De quanto em quanto tempo o aviso longo de "estou aguardando alguém" se
#: repete. No intervalo o bot responde curto — mas responde.
_MINUTOS_ENTRE_AVISOS = 3.0


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
    """A resposta é morna o bastante para NÃO virar cobrança?

    Olha cada pedaço da frase, e não só o começo. Antes a checagem era
    `limpo == m or limpo.startswith(m + " ")`, e bastava uma vírgula para
    furar: "acho que sim, pode ser" — duas respostas mornas emendadas — passava
    direto e gerava Pix. Foi o que dois testes de conversa encontraram.

    Na dúvida, morna: o custo de errar para este lado é uma pergunta a mais; o
    custo de errar para o outro é cobrar quem não concordou.
    """
    limpo = normalize(text).strip(" .!?")
    pedacos = [p.strip(" .!?") for p in re.split(r"[,;]| e | mas ", limpo)]
    return any(
        pedaco == m or pedaco.startswith(m + " ")
        for pedaco in pedacos
        if pedaco
        for m in _MORNAS
    )


# ---------------------------------------------------------------------------
# Situação (o que a IA recebe junto com a mensagem)
# ---------------------------------------------------------------------------

def describe_situation(deps: AgentDeps, session: ConversationSession) -> str:
    """Retrato do pedido agora, em português, para o modelo.

    A lista é UMA só e numerada como o cliente a vê — item completo e item em
    montagem no mesmo lugar. É isto que deixa "esse mesmo", "o segundo", "tira
    o médio" e "1 e 3" serem resolvidos sem obrigar o cliente a repetir nomes.
    """
    linhas: list[str] = []

    if session.cart.is_empty:
        linhas.append("Pedido vazio — o cliente ainda não escolheu nada.")
    else:
        linhas.append("Itens do pedido (use ESTES números em item_index):")
        faltando: list[str] = []
        for i, item in enumerate(session.cart.items, start=1):
            sabores = (
                f" ({', '.join(c.name for c in item.complements)})"
                if item.complements
                else ""
            )
            group = open_group(deps, item)
            if group is None:
                linhas.append(f"{i}. {item.quantity}x {item.product_name}{sabores} — completo")
                continue
            escolhidos = [c.name for c in item.complements if c.group_id == group.id]
            faltam = max(group.min_choices - len(escolhidos), 0)
            linhas.append(
                f"{i}. {item.quantity}x {item.product_name}{sabores} — EM MONTAGEM, "
                f"falta{'m' if faltam != 1 else ''} {faltam} de {group.min_choices} sabores"
            )
            disponiveis = [
                c.name for c in group.available_complements if c.name not in escolhidos
            ]
            faltando.append(
                f"Sabores que ainda cabem no item {i}: " + ", ".join(disponiveis)
            )
        linhas += faltando

    kind = fulfillment_of(session)
    if kind is not None:
        linhas.append(f"Forma de entrega já definida: {kind.value}.")

    endereco = address_of(session)
    if endereco:
        ausentes = missing_address_fields(endereco)
        linhas.append(
            f"Endereço incompleto, falta: {', '.join(ausentes)}."
            if ausentes
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
            "Última lista de opções mostrada a ele: " + ", ".join(ultima)
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
    adopt_legacy_draft(deps, session)

    voltou_do_humano = False
    if session.handoff or session.state is S.ATENDIMENTO_HUMANO:
        if human_on_the_line(session):
            resposta = _handoff_turn(session, plan, text)
            if resposta is not None:
                return resposta
            voltou_do_humano = True
        else:
            logger.info("handoff sem resposta humana; o bot reassume a conversa")
            resume_from_human(session)

    if session.state in {S.CONCLUIDO, S.CANCELADO}:
        # Mensagem nova depois de um pedido fechado abre um ciclo limpo.
        _go(session, S.CONVERSANDO)
        session.slots = {k: v for k, v in session.slots.items() if k == "customer_name"}
        session.cart.items.clear()
        session.active_order_id = None

    if session.state is S.AGUARDANDO_PAGAMENTO and plan.has_any(_MEXEM_NO_PEDIDO):
        # Com Pix emitido, o carrinho está vazio (`place_order` o esvaziou) e
        # mexer nele montaria um SEGUNDO pedido por baixo do primeiro: o bot
        # dizia "Seu pedido: R$ 9,00" para quem tinha um Pix de R$ 73,00
        # aberto. Um cliente simulado caiu exatamente nisso.
        #
        # A garantia é da máquina de estados: pagamento pendente congela o
        # pedido. Perguntar, cancelar e chamar gente continuam funcionando.
        return [r.order_awaiting_payment()]

    if plan.customer_name and "customer_name" not in session.slots:
        session.slots["customer_name"] = plan.customer_name

    primeira_vez = not session.slots.get("ja_falamos")
    session.slots["ja_falamos"] = True

    turn = Turn()

    # A confirmação é a única operação que mexe em dinheiro: ela sai da fila e
    # só vale se houver um resumo na tela esperando resposta.
    #
    # close_order conta como confirmação NESTE ponto específico: com o resumo
    # já na tela, "fechou mano, pode mandar" e "tá certo isso, manda" saem do
    # modelo como close_order, não confirm_order — e sem isto o bot só
    # reexibia o mesmo resumo, obrigando o cliente a repetir a confirmação de
    # um jeito mais formal. A trava da resposta morna (`_hedged`) continua
    # valendo do mesmo jeito para os dois casos.
    quer_confirmar = session.slots.get(AWAITING_CONFIRM) and (
        plan.has(Action.CONFIRM_ORDER) or plan.has(Action.CLOSE_ORDER)
    )
    if quer_confirmar:
        if _hedged(text):
            # "pode ser", "acho que sim": o modelo classifica isso como
            # confirmação, mas não é um sim. Cobrança não se faz com
            # quase-certeza — o cliente responde uma vez mais, e aí sim.
            return [r.confirm_once_more()]
        if pending_index(deps, session) is None:
            session.slots.pop(AWAITING_CONFIRM, None)
            return await place_order(deps, session)

    for op in plan.operations:
        await apply(deps, session, op, turn, text)
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
    deps: AgentDeps, session: ConversationSession, plan: AgentPlan, turn: Turn
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
        ja_mostrou = any("*Seu pedido*" in nota for nota in turn.notes)
        retomada = _resume_prompt(deps, session, carrinho_na_tela=ja_mostrou)
        return turn.notes + ([retomada] if retomada else [])

    # 2. Tem item em montagem: falta escolher sabor. Vale mesmo que ele tenha
    #    pedido para fechar — não se fecha pedido pela metade.
    index = pending_index(deps, session)
    if index is not None:
        item = session.cart.items[index]
        group = open_group(deps, item)
        product = product_of(deps, item)
        if product is not None and group is not None:
            session.fail_count = 0
            session.slots[LAST_OFFER] = [c.name for c in group.available_complements]
            escolhidos = [c.name for c in item.complements if c.group_id == group.id]
            pergunta = r.ask_flavors(
                product,
                group,
                escolhidos,
                posicao=index + 1 if len(session.cart.items) > 1 else None,
            )
            # Ele já pediu para fechar: explica o que está segurando, senão a
            # mesma pergunta repetida parece o bot ignorando o "pode fechar".
            if session.slots.get(CLOSING):
                return turn.notes + [r.missing_before_closing(product), pergunta]
            return turn.notes + [pergunta]

    # 3. Fechando o pedido.
    if session.slots.get(CLOSING) and not session.cart.is_empty:
        session.fail_count = 0
        return turn.notes + await _checkout_step(deps, session)

    # 4. Mexeu no pedido: confirma e pergunta se quer mais.
    if turn.changed:
        session.fail_count = 0
        session.slots.pop(AWAITING_CONFIRM, None)
        if session.cart.is_empty:
            return turn.notes + [menu(deps, session)]
        return turn.notes + [r.ask_more_or_close(session.cart)]

    # 5. Cumprimento, agradecimento, conversa fiada: abre o atendimento em vez
    #    de dizer "não entendi" a quem só disse oi. Com um Pix já emitido e
    #    ainda pendente, "carrinho vazio, o que você vai querer?" soa como se
    #    o pedido tivesse sumido — fala do pedido em aberto em vez do cardápio.
    if plan.has(Action.NO_ACTION) and session.cart.is_empty:
        session.fail_count = 0
        if session.active_order_id is not None:
            return turn.notes + [await pending_order_status(deps, session)]
        return turn.notes + [menu(deps, session)]

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


def _resume_prompt(
    deps: AgentDeps,
    session: ConversationSession,
    *,
    carrinho_na_tela: bool = False,
) -> str | None:
    """A pergunta do ponto em que o pedido está, para retomar depois de uma dúvida.

    `carrinho_na_tela` evita o resumo em duplicata: quem pediu "me mostra o
    carrinho" acabou de recebê-lo, e repetir a lista inteira logo abaixo para
    emendar a pergunta é exatamente o tipo de resposta que parece robô.
    """
    index = pending_index(deps, session)
    if index is not None:
        item = session.cart.items[index]
        group = open_group(deps, item)
        product = product_of(deps, item)
        if product is not None and group is not None:
            escolhidos = [c.name for c in item.complements if c.group_id == group.id]
            return r.resume_flavors(product, group, escolhidos)
    if session.slots.get(AWAITING_CONFIRM):
        return r.ask_confirm_short()
    if session.slots.get(CLOSING) and fulfillment_of(session) is None:
        return r.ask_fulfillment()
    if not session.cart.is_empty:
        return (
            r.ask_more_short()
            if carrinho_na_tela
            else r.ask_more_or_close(session.cart)
        )
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
        return [r.didnt_get_it(), *([retomada] if retomada else [])]
    if session.fail_count == 2:
        return [r.didnt_get_it_again(), *([retomada] if retomada else [])]

    session.fail_count = 0
    return [r.offer_human(), *([retomada] if retomada else [])]
