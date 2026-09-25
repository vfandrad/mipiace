"""Os casos de avaliação do agente — uma lista, dois modos de execução.

Por que este arquivo existe
---------------------------
Os testes do executor escrevem o plano da IA à mão: dado `UPDATE_ITEM` com
`remove_flavors=["Morango"]`, o pedido é editado. Isso prova que o executor
está certo, e não prova nada sobre a pergunta que importa de verdade — **"troca
morango por chocolate" vira mesmo um UPDATE_ITEM?**. A tradução da linguagem em
operação era a única parte do agente sem cobertura nenhuma.

Os casos ficam aqui, sozinhos, porque são lidos por dois testes:

* `test_agent_eval.py` roda sempre, offline. Alimenta o executor com o plano
  ESPERADO de cada caso e confere o efeito no pedido. Custo zero, e garante que
  o que o modelo deveria devolver de fato produz o resultado certo.
* `test_agent_eval_live.py` roda sob demanda (`pytest -m eval`) contra a
  OpenAI. Manda a mensagem de verdade e compara o plano que voltou com o
  esperado. É este que responde à pergunta acima — e é por isso que gasta token
  e fica fora da execução padrão.

Como escrever um caso
---------------------
`mensagem` é o que o cliente digita, do jeito que aparece no WhatsApp: solto,
sem acento, com erro de digitação. `preparar` leva a conversa até o ponto em
que a fala faz sentido. `acao` é o que a IA deveria entender; `verificar` olha
o pedido depois que o executor aplicou.

Nada aqui deve virar palavra-chave no código do agente. Estes exemplos existem
para MEDIR generalização, não para ser programados um a um — um agente que só
passa porque alguém escreveu `if "troca" in texto` falhou no que importa.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.plan import Action, Address, Operation
from app.domain.enums import ConversationState as S

Preparar = Callable[[Any, Any], Awaitable[None]]
Verificar = Callable[[Any, Any, list[str]], None]


@dataclass(frozen=True)
class EvalCase:
    """Um caso: a fala do cliente, o que a IA deveria entender, o que sai disso."""

    id: str
    mensagem: str
    #: Por que este caso existe. Sai no relatório do eval ao vivo.
    porque: str = ""
    #: O que o cliente já fez antes desta mensagem.
    preparar: Preparar | None = None
    #: A ação principal que a IA deveria devolver.
    acao: Action = Action.NO_ACTION
    #: Outras leituras aceitáveis da mesma fala. Ambiguidade de verdade existe,
    #: e reprovar o modelo por escolher a segunda melhor seria medir errado.
    tambem: tuple[Action, ...] = ()
    #: Campos da operação principal que precisam bater.
    campos: dict[str, Any] = field(default_factory=dict)
    #: Operações além da principal, quando a mensagem carrega várias.
    extras: tuple[Operation, ...] = ()
    #: Confere o pedido depois que o executor aplicou o plano.
    verificar: Verificar | None = None

    def plano_esperado(self) -> list[Operation]:
        """O plano que a IA deveria ter produzido para esta mensagem."""
        return [Operation(action=self.acao, **self.campos), *self.extras]

    def acoes_aceitas(self) -> set[Action]:
        return {self.acao, *self.tambem}


# ---------------------------------------------------------------------------
# Preparo — levam a conversa até o ponto de cada caso
# ---------------------------------------------------------------------------
# Os imports são tardios para este módulo poder ser lido (e a lista de casos
# inspecionada) sem arrastar o executor e o catálogo de teste junto.


async def pote_montado(deps: Any, session: Any) -> None:
    """Um Pote 500ml completo, com Pistache e Morango."""
    from tests.test_agent_machine import montar_pote  # noqa: PLC0415

    await montar_pote(deps, session)


async def dois_itens(deps: Any, session: Any) -> None:
    """Pote 500ml (item 1) e Pote 240ml (item 2), ambos completos."""
    from app.agent.machine import run  # noqa: PLC0415
    from tests.test_agent_machine import montar_pote, op, plano  # noqa: PLC0415

    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 240ml", add_flavors=["Pistache"])),
        "e um medio de pistache",
    )


async def duas_casquinhas(deps: Any, session: Any) -> None:
    """2x Casquinha, único item do carrinho."""
    from app.agent.machine import run  # noqa: PLC0415
    from tests.test_agent_machine import op, plano  # noqa: PLC0415

    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Casquinha", quantity=2)),
        "quero 2 casquinhas",
    )


async def esperando_o_bairro(deps: Any, session: Any) -> None:
    """Pedido pronto, entrega escolhida, endereço só sem o bairro.

    É o ponto exato em que o bot pergunta "qual o bairro?" — e onde o modelo
    já inventou um ("Jardim América") ao receber um simples "sim".
    """
    from app.agent.machine import run  # noqa: PLC0415
    from tests.test_agent_machine import op, plano  # noqa: PLC0415

    await pote_montado(deps, session)
    await run(
        deps,
        session,
        plano(
            op(
                Action.UPDATE_ADDRESS,
                address=Address(rua="Rua das Flores", numero="128"),
            ),
            op(Action.CLOSE_ORDER),
        ),
        "entrega na rua das flores 128, pode fechar",
    )


async def resumo_na_tela(deps: Any, session: Any) -> None:
    """Pedido fechado em retirada, com o resumo final esperando o "sim"."""
    from app.agent.machine import run  # noqa: PLC0415
    from tests.test_agent_machine import op, plano  # noqa: PLC0415

    await pote_montado(deps, session)
    await run(
        deps,
        session,
        plano(
            op(Action.SET_FULFILLMENT, fulfillment="retirada"),
            op(Action.CLOSE_ORDER),
        ),
        "pode fechar, vou retirar",
    )


# ---------------------------------------------------------------------------
# Verificações — o que tem de ser verdade sobre o pedido no fim do turno
# ---------------------------------------------------------------------------


def sabores_do_item(*esperados: str) -> Verificar:
    def checar(deps: Any, session: Any, replies: list[str]) -> None:
        atuais = {c.name for c in session.cart.items[0].complements}
        assert atuais == set(esperados), f"sabores: {sorted(atuais)}"

    return checar


def continua_com_um_item(deps: Any, session: Any, replies: list[str]) -> None:
    """A regra que mais custou dinheiro: corrigir não pode criar item novo."""
    assert len(session.cart.items) == 1, (
        f"o pedido ficou com {len(session.cart.items)} itens — uma correção "
        "virou item novo e o cliente pagaria duas vezes"
    )


def trocou_o_sabor(deps: Any, session: Any, replies: list[str]) -> None:
    continua_com_um_item(deps, session, replies)
    sabores_do_item("Pistache", "Chocolate")(deps, session, replies)


def sobrou_so_o_medio(deps: Any, session: Any, replies: list[str]) -> None:
    nomes = [i.product_name for i in session.cart.items]
    assert nomes == ["Pote 240ml"], f"sobraram: {nomes}"


def ficou_cancelado(deps: Any, session: Any, replies: list[str]) -> None:
    assert session.state is S.CANCELADO, f"estado: {session.state}"
    assert session.cart.is_empty, "cancelar tem de esvaziar o pedido"


def escalou_sem_emudecer(deps: Any, session: Any, replies: list[str]) -> None:
    assert session.handoff, "não entrou em atendimento humano"
    assert replies, "handoff nunca pode virar silêncio — era o defeito mais caro"


def nao_inventou_bairro(deps: Any, session: Any, replies: list[str]) -> None:
    """Endereço é o único dado do pedido sem catálogo para contradizer a IA."""
    endereco = session.slots.get("address") or {}
    assert not endereco.get("bairro"), (
        f"bairro inventado a partir de um \"sim\": {endereco.get('bairro')!r} — "
        "a entrega iria para o lugar errado"
    )


def pedido_nao_duplicou(deps: Any, session: Any, replies: list[str]) -> None:
    """"pode fechar" não é "peça tudo de novo"."""
    nomes = [i.product_name for i in session.cart.items]
    assert len(nomes) == len(set(nomes)), f"o pedido duplicou: {nomes}"


def anotou_entrega_e_endereco(deps: Any, session: Any, replies: list[str]) -> None:
    assert session.slots.get("fulfillment") == "entrega", session.slots
    endereco = session.slots.get("address") or {}
    assert endereco.get("numero") == "123", endereco


def trocou_uma_unidade_por_produto_novo(deps: Any, session: Any, replies: list[str]) -> None:
    """"troca uma casquinha por um pote" tem que tirar UMA casquinha, não deixar as duas."""
    quantidades = {i.product_name: i.quantity for i in session.cart.items}
    assert quantidades.get("Casquinha") == 1, (
        f"a casquinha antiga não saiu do pedido: {quantidades} — o cliente pagaria "
        "pelas duas casquinhas mais o pote novo"
    )
    assert "Pote 240ml" in quantidades, f"o pote novo não entrou: {quantidades}"


def escolheu_retirada(deps: Any, session: Any, replies: list[str]) -> None:
    assert session.slots.get("fulfillment") == "retirada", session.slots
    continua_com_um_item(deps, session, replies)


# ---------------------------------------------------------------------------
# Os casos
# ---------------------------------------------------------------------------

CASES: tuple[EvalCase, ...] = (
    # --- Criar o pedido ---------------------------------------------------
    EvalCase(
        id="criar_direto",
        mensagem="quero um pote 500ml de pistache e morango",
        porque="o caminho feliz: produto e sabores numa frase só",
        acao=Action.ADD_ITEM,
        campos={"product_name": "Pote 500ml", "add_flavors": ["Pistache", "Morango"]},
        verificar=sabores_do_item("Pistache", "Morango"),
    ),
    EvalCase(
        id="linguagem_solta",
        mensagem="manda um pote de 500 de chocolate e pistache",
        porque="ninguém digita o nome do cardápio; 'manda um' também é pedido",
        acao=Action.ADD_ITEM,
        campos={"product_name": "Pote 500ml", "add_flavors": ["Chocolate", "Pistache"]},
        verificar=sabores_do_item("Chocolate", "Pistache"),
    ),
    EvalCase(
        id="erro_de_digitacao",
        mensagem="keria um pote 500 de pistach e morango",
        porque="WhatsApp é digitado no corre; erro de digitação é o normal",
        acao=Action.ADD_ITEM,
        campos={"product_name": "Pote 500ml", "add_flavors": ["Pistache", "Morango"]},
        verificar=sabores_do_item("Pistache", "Morango"),
    ),
    # --- Corrigir o que já existe -----------------------------------------
    EvalCase(
        id="trocar_sabor",
        mensagem="troca o morango por chocolate",
        porque="o defeito mais caro do agente: trocar virava adicionar",
        preparar=pote_montado,
        acao=Action.UPDATE_ITEM,
        campos={"remove_flavors": ["Morango"], "add_flavors": ["Chocolate"]},
        verificar=trocou_o_sabor,
    ),
    EvalCase(
        id="remover_pelo_ordinal",
        mensagem="tira o primeiro",
        porque="ordinal tem de virar o número do item que o cliente viu na tela",
        preparar=dois_itens,
        acao=Action.REMOVE_ITEM,
        campos={"item_index": 1},
        verificar=sobrou_so_o_medio,
    ),
    EvalCase(
        id="tirar_sabor_nao_tira_item",
        mensagem="tira o pistache",
        porque="'tira o pistache' é sabor, não item — apagar o pote perde a venda",
        preparar=pote_montado,
        acao=Action.UPDATE_ITEM,
        tambem=(Action.REMOVE_ITEM,),
        campos={"remove_flavors": ["Pistache"]},
        verificar=continua_com_um_item,
    ),
    EvalCase(
        id="mudar_quantidade",
        mensagem="coloca mais dois desses",
        porque="'mais dois' mexe no que existe; não é um pedido novo do zero",
        preparar=pote_montado,
        acao=Action.UPDATE_QUANTITY,
        tambem=(Action.DUPLICATE_ITEM,),
        campos={"quantity": 3},
    ),
    # --- Perguntas que não mexem no pedido --------------------------------
    EvalCase(
        id="quanto_ficou",
        mensagem="quanto ficou?",
        porque="pergunta no meio do fluxo não pode derrubar o pedido",
        preparar=pote_montado,
        acao=Action.SHOW_TOTAL,
        verificar=continua_com_um_item,
    ),
    EvalCase(
        id="ver_carrinho",
        mensagem="me mostra meu pedido",
        porque="consultar o carrinho é leitura pura",
        preparar=pote_montado,
        acao=Action.SHOW_CART,
        verificar=continua_com_um_item,
    ),
    EvalCase(
        id="tem_esse_sabor",
        mensagem="tem pistache hoje?",
        porque="disponibilidade sai do catálogo do dia, não da memória do modelo",
        acao=Action.ANSWER_QUESTION,
        campos={"question_topic": "disponibilidade", "raw_text": "pistache"},
    ),
    EvalCase(
        id="produto_que_nao_existe",
        mensagem="tem milkshake?",
        porque="a IA não inventa produto; quem diz o que existe é o catálogo",
        acao=Action.ANSWER_QUESTION,
        campos={"question_topic": "disponibilidade", "raw_text": "milkshake"},
    ),
    EvalCase(
        id="forma_de_pagamento",
        mensagem="vocês aceitam cartão?",
        porque="quatro dos dez clientes simulados ouviram 'não entendi' aqui",
        acao=Action.ANSWER_QUESTION,
        campos={"question_topic": "pagamento"},
    ),
    # --- Fechar, mudar de ideia, confirmar, desistir -----------------------
    EvalCase(
        id="fechar_informal",
        mensagem="fechou, pode mandar",
        porque="ninguém digita 'confirmar'; fechar se diz de vinte jeitos",
        preparar=pote_montado,
        acao=Action.CLOSE_ORDER,
    ),
    EvalCase(
        id="mudar_para_retirada",
        mensagem="na verdade quero retirar na loja",
        porque="mudar de ideia no meio do fluxo não recomeça o pedido",
        preparar=pote_montado,
        acao=Action.SET_FULFILLMENT,
        campos={"fulfillment": "retirada"},
        verificar=escolheu_retirada,
    ),
    EvalCase(
        id="confirmar_o_resumo",
        mensagem="isso mesmo, pode mandar o pix",
        porque="a única operação que gera cobrança",
        preparar=resumo_na_tela,
        acao=Action.CONFIRM_ORDER,
    ),
    EvalCase(
        id="cancelar",
        mensagem="deixa pra lá",
        porque="desistir é uma fala curta e informal como qualquer outra",
        preparar=pote_montado,
        acao=Action.CANCEL_ORDER,
        verificar=ficou_cancelado,
    ),
    EvalCase(
        id="falar_com_gente",
        mensagem="queria falar com alguém aí",
        porque="escalar para humano não pode calar o bot",
        acao=Action.REQUEST_HUMAN,
        verificar=escalou_sem_emudecer,
    ),
    # --- Ambiguidade: perguntar é melhor que chutar caro -------------------
    EvalCase(
        id="dois_potes_sem_tamanho",
        mensagem="quero dois potes",
        porque="pode ser 2 médios ou 2 grandes; chutar custa R$ 28 ao cliente",
        acao=Action.ASK_CLARIFICATION,
        tambem=(Action.ANSWER_QUESTION, Action.SHOW_MENU),
        campos={"clarification": "Qual tamanho você quer?"},
    ),
    # --- O que as conversas de teste encontraram ---------------------------
    EvalCase(
        id="sim_nao_e_bairro",
        mensagem="sim",
        porque=(
            "respondendo 'qual o bairro?', o modelo preencheu 'Jardim América' — "
            "um bairro que ninguém digitou. Entrega no lugar errado."
        ),
        preparar=esperando_o_bairro,
        acao=Action.NO_ACTION,
        tambem=(Action.ASK_CLARIFICATION, Action.CLOSE_ORDER, Action.UPDATE_ADDRESS),
        verificar=nao_inventou_bairro,
    ),
    EvalCase(
        id="fechar_nao_repete_o_pedido",
        mensagem="pode fechar",
        porque=(
            "o modelo reemitia os add_item da primeira mensagem ao ver o "
            "histórico, e o cliente pagava o pedido duas vezes"
        ),
        preparar=dois_itens,
        acao=Action.CLOSE_ORDER,
        verificar=pedido_nao_duplicou,
    ),

    # --- Uma mensagem, várias operações -----------------------------------
    EvalCase(
        id="tres_operacoes_de_uma_vez",
        mensagem=(
            "quero um pote 500ml de pistache e morango, "
            "entrega na Rua das Flores, 123, Centro"
        ),
        porque="o cliente não deve repetir o que já disse numa frase só",
        acao=Action.ADD_ITEM,
        tambem=(Action.SET_FULFILLMENT, Action.UPDATE_ADDRESS),
        campos={"product_name": "Pote 500ml", "add_flavors": ["Pistache", "Morango"]},
        extras=(
            Operation(action=Action.SET_FULFILLMENT, fulfillment="entrega"),
            Operation(
                action=Action.UPDATE_ADDRESS,
                address=Address(rua="Rua das Flores", numero="123", bairro="Centro"),
            ),
        ),
        verificar=anotou_entrega_e_endereco,
    ),

    # --- O que a segunda rodada de conversas de teste encontrou -----------
    EvalCase(
        id="sabor_repetido_nao_apaga_item",
        mensagem="quero os dois de pistache, os 2 iguais",
        porque=(
            "pedir o mesmo sabor duas vezes fez o modelo devolver remove_item "
            "e apagar o único item do carrinho — sabor repetido tem que ser "
            "recusado (o executor já sabe fazer isso), nunca motivo para "
            "apagar o pedido"
        ),
        preparar=pote_montado,
        acao=Action.UPDATE_ITEM,
        campos={"add_flavors": ["Pistache"]},
        verificar=continua_com_um_item,
    ),
    EvalCase(
        id="mais_um_pote_sem_especificar",
        mensagem="bota mais um pote",
        porque=(
            "sem tamanho nem sabor, o modelo copiou o último item (tamanho e "
            "sabores) e já somou R$ 32 ao carrinho sem perguntar nada — "
            "inventar configuração é o que a arquitetura do agente proíbe"
        ),
        preparar=pote_montado,
        acao=Action.ASK_CLARIFICATION,
        tambem=(Action.DUPLICATE_ITEM,),
        campos={"clarification": "Qual tamanho e quais sabores você quer nesse outro?"},
    ),
    EvalCase(
        id="atendente_junto_com_pedido_nao_some",
        mensagem="quero também uma casquinha, mas na verdade chama um atendente humano pra mim",
        porque=(
            "pedir atendente na mesma mensagem que um item fez o modelo "
            "devolver só add_item — o pedido de atendente sumiu e o cliente "
            "teve que repetir"
        ),
        preparar=pote_montado,
        acao=Action.REQUEST_HUMAN,
    ),

    # --- O que a terceira rodada de testes encontrou -----------------------
    EvalCase(
        id="trocar_uma_unidade_por_produto_diferente",
        mensagem="troca uma das casquinhas por um pote de 240ml de pistache",
        porque=(
            '"troca X por Y" com produtos DIFERENTES (não sabor/tamanho do '
            "mesmo item) às vezes só adicionava o Y e esquecia de tirar uma "
            "unidade do X — o cliente pagava pelas duas casquinhas mais o "
            "pote novo, em vez de uma casquinha a menos"
        ),
        preparar=duas_casquinhas,
        acao=Action.REMOVE_ITEM,
        tambem=(Action.UPDATE_QUANTITY,),
        campos={"quantity": 1, "product_name": "Casquinha"},
        extras=(Operation(action=Action.ADD_ITEM, product_name="Pote 240ml", add_flavors=["Pistache"]),),
        verificar=trocou_uma_unidade_por_produto_novo,
    ),

    # --- O que a quarta rodada de testes encontrou --------------------------
    EvalCase(
        id="pergunta_junto_com_item_novo_nao_some",
        mensagem="e uma casquinha também, vocês tem maracuja hoje?",
        porque=(
            "um pedido de item e uma pergunta de disponibilidade na mesma "
            "mensagem — a pergunta sumiu do plano numa conversa de teste "
            "real, só o item foi registrado"
        ),
        preparar=pote_montado,
        acao=Action.ANSWER_QUESTION,
        campos={"question_topic": "disponibilidade", "raw_text": "maracuja"},
    ),
)
