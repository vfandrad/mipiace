"""O prompt: a IA traduz a mensagem em operações, e só isso.

A regra que rege este arquivo, e que separa "dar liberdade" de "dar autoridade":

> A IA tem liberdade total para interpretar linguagem natural e decidir qual
> operação o cliente está tentando realizar. Ela NUNCA tem autoridade para
> inventar produto, preço, taxa ou disponibilidade, nem para executar
> diretamente qualquer coisa que envolva dinheiro. Ela traduz; o backend
> valida contra o catálogo real e aplica.

Por isso o modelo recebe três coisas a cada turno: as instruções, o cardápio
do dia (universo fechado, com `cache_control` porque é grande e repetido) e a
SITUAÇÃO do pedido agora — o que está no carrinho, o que falta no item em
construção, o que acabamos de perguntar. É a situação que deixa "esse mesmo",
"o segundo", "pode ser" e "1 e 3" serem resolvidos sem obrigar o cliente a
falar como formulário.
"""

from __future__ import annotations

from typing import Any

from app.agent.plan import QUESTION_TOPICS, Action
from app.core.config import get_settings
from app.domain.catalog import CatalogSnapshot

#: Nome da tool. O modelo é forçado a chamá-la (tool_choice), então ela é o
#: único formato de saída possível — não há texto livre para parsear.
TOOL_NAME = "registrar_operacoes"

_ACTION_DESCRIPTIONS = {
    Action.ADD_ITEM: (
        "quer um item NOVO no pedido. product_name = nome exato do cardápio; "
        "add_flavors = sabores que ele já disse; quantity se ele deu"
    ),
    Action.UPDATE_ITEM: (
        "quer MUDAR um item que já existe: trocar, tirar ou acrescentar sabor. "
        '"troca o chocolate por fior di latte" -> remove_flavors=["Chocolate"], '
        'add_flavors=["Fior di latte"]. NUNCA use add_item para isso'
    ),
    Action.REPLACE_ITEM: (
        'trocar o PRODUTO do item mantendo o resto: "na verdade queria o médio"'
    ),
    Action.REMOVE_ITEM: (
        'tirar um item do pedido: "remove o item 1", "tira o segundo", '
        '"quero só um pote". Use item_index quando ele apontar qual. Se ele '
        'disser QUANTOS tirar ("tira uma casquinha" havendo 3), mande também '
        "quantity com esse número — sem ele a linha inteira sai"
    ),
    Action.UPDATE_QUANTITY: (
        '"quero 3 cascões", "coloca mais dois", "na verdade só um"'
    ),
    Action.DUPLICATE_ITEM: (
        '"quero outro igual", "mais um desses" — SÓ quando é uma cópia do '
        "mesmo item. Se ele nomear outro produto, use add_item"
    ),
    Action.SET_FULFILLMENT: (
        'como ele quer receber, dito de qualquer jeito: "manda aqui em casa", '
        '"vou buscar aí", "passo aí pegar", "entrega" -> fulfillment'
    ),
    Action.UPDATE_ADDRESS: "mandou endereço, inteiro ou um pedaço dele",
    Action.SHOW_MENU: "quer ver o cardápio/as opções/os sabores",
    Action.SHOW_CART: '"me mostra o carrinho", "o que eu pedi?"',
    Action.SHOW_TOTAL: '"quanto deu?", "quanto ficou?", "qual o total?"',
    Action.ANSWER_QUESTION: (
        "fez uma PERGUNTA informativa (preço, horário, taxa, prazo, se tem tal "
        "sabor, onde fica a loja). Preencha question_topic e question_text. "
        "NÃO mexe no pedido — o cliente continua exatamente de onde estava"
    ),
    Action.CLOSE_ORDER: (
        'quer fechar, dito como for: "pode fechar", "é só isso", "só isso '
        'mesmo", "pode mandar", "tá certo", "pode finalizar", "manda o pix"'
    ),
    Action.CONFIRM_ORDER: (
        "disse SIM ao resumo final que acabamos de mostrar. Use APENAS se a "
        "situação disser que há um resumo aguardando confirmação e a resposta "
        'for claramente positiva. Na dúvida ("pode ser", "acho que sim"), use '
        "ask_clarification — esta ação gera cobrança"
    ),
    Action.CANCEL_ORDER: (
        "quer desistir do pedido INTEIRO (não de um item). Vale para o que as "
        'pessoas dizem de verdade ao desistir: "cancela", "desisti", "deixa '
        'pra lá", "esquece", "não quero mais", "melhor não". Havendo pedido em '
        "andamento, essas falas são cancelamento — não são conversa fiada"
    ),
    Action.REQUEST_HUMAN: "quer falar com uma pessoa do time",
    Action.ASK_CLARIFICATION: (
        "há duas leituras possíveis e escolher seria chutar. Ex.: \"quero dois "
        'potes" pode ser 2 médios ou o GG. Preencha clarification com o que '
        "precisa ser perguntado. Prefira isto a errar"
    ),
    Action.NO_ACTION: (
        "cumprimento, agradecimento, desabafo — nada a fazer com o pedido"
    ),
}


def tool_schema() -> dict[str, Any]:
    """input_schema espelhando `AgentPlan`."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Registra, em forma de operações, tudo o que o cliente quis dizer "
            "nesta mensagem. Use SEMPRE esta ferramenta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": (
                        "Uma entrada por coisa que o cliente quer. Uma mensagem "
                        "pode ter várias: \"tira o primeiro, põe um grande de "
                        "chocolate e quero entrega\" são três operações. Ordem "
                        "importa: aplique na ordem em que ele falou."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [a.value for a in Action],
                                "description": "\n".join(
                                    f"{action.value}: {desc}"
                                    for action, desc in _ACTION_DESCRIPTIONS.items()
                                ),
                            },
                            "item_index": {
                                "type": ["integer", "null"],
                                "description": (
                                    "Qual item do pedido, contando a partir de 1 "
                                    "na ordem em que o carrinho foi mostrado."
                                ),
                            },
                            "product_name": {
                                "type": ["string", "null"],
                                "description": (
                                    "NOME EXATO do item do cardápio, copiado da "
                                    'lista. Use tamanho, volume, descrição e o '
                                    'contexto: "o grande", "o de 500", "esse '
                                    'mesmo" são itens do cardápio. Nulo se não '
                                    "houver item claro."
                                ),
                            },
                            "quantity": {"type": ["integer", "null"]},
                            "add_flavors": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Nomes EXATOS de sabores do cardápio que ele "
                                    "escolheu NESTA mensagem. Se respondeu por "
                                    "número, traduza usando a lista mostrada. "
                                    "Não repita o que ele já tinha escolhido."
                                ),
                            },
                            "remove_flavors": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Sabores que ele quer TIRAR do item.",
                            },
                            "fulfillment": {
                                "type": ["string", "null"],
                                "description": 'Exatamente "entrega" ou "retirada".',
                            },
                            "address": {
                                "type": ["object", "null"],
                                "properties": {
                                    "rua": {"type": ["string", "null"]},
                                    "numero": {"type": ["string", "null"]},
                                    "bairro": {"type": ["string", "null"]},
                                    "complemento": {"type": ["string", "null"]},
                                    "referencia": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "rua",
                                    "numero",
                                    "bairro",
                                    "complemento",
                                    "referencia",
                                ],
                                "additionalProperties": False,
                            },
                            "question_topic": {
                                "type": ["string", "null"],
                                "description": "Um destes: " + ", ".join(QUESTION_TOPICS),
                            },
                            "question_text": {"type": ["string", "null"]},
                            "raw_text": {
                                "type": ["string", "null"],
                                "description": (
                                    "Trecho literal do que ele pediu quando isso "
                                    "NÃO existe no cardápio (\"açaí\", "
                                    '"milkshake"). É assim que o sistema '
                                    'responde "não trabalhamos com isso".'
                                ),
                            },
                            "clarification": {"type": ["string", "null"]},
                        },
                        # `strict` da OpenAI exige TODAS as chaves em required
                        # (as opcionais aceitando null). Sem isso o gpt-4o-mini
                        # devolvia operação sem o campo `action` — o pedido
                        # inteiro virava "no_action" e o cliente ouvia que não
                        # tinha sido entendido.
                        "required": [
                            "action",
                            "item_index",
                            "product_name",
                            "quantity",
                            "add_flavors",
                            "remove_flavors",
                            "fulfillment",
                            "address",
                            "question_topic",
                            "question_text",
                            "raw_text",
                            "clarification",
                        ],
                        "additionalProperties": False,
                    },
                },
                "confidence": {"type": "number"},
                "customer_name": {"type": ["string", "null"]},
            },
            "required": ["operations", "confidence", "customer_name"],
            "additionalProperties": False,
        },
    }


def compact_catalog(catalog: CatalogSnapshot) -> str:
    """Cardápio em texto enxuto — é o universo fechado do modelo."""
    lines: list[str] = []
    for product in catalog.available_products:
        descricao = f" — {product.description}" if product.description else ""
        preco = f"R$ {product.base_price:.2f}".replace(".", ",")
        lines.append(f"- {product.name} ({preco}){descricao}")
        for group in product.groups:
            nomes = ", ".join(c.name for c in group.available_complements)
            if not nomes:
                continue
            regra = f"escolhe {group.min_choices} a {group.max_choices}, sem repetir"
            lines.append(f"    [{group.name} | {regra}]: {nomes}")
    esgotados = [p.name for p in catalog.products if not p.is_available]
    if esgotados:
        lines.append("(hoje sem: " + ", ".join(esgotados) + ")")
    return "\n".join(lines) or "(cardápio vazio)"


#: O molde das instruções. `{loja}` e `{ramo}` vêm da configuração: o sistema
#: não sabe de antemão que é uma gelateria, e não deve saber.
BASE_INSTRUCTIONS_TEMPLATE = """Você é o tradutor de um atendimento de {ramo} \
brasileira ({loja}) pelo WhatsApp.

O cliente fala como quiser: solto, com erro de digitação, sem acento, em \
vários pedaços, por número, por apelido ou por "esse mesmo". Seu trabalho é \
entender e registrar em OPERAÇÕES. Quem responde ao cliente, calcula preço, \
aplica taxa e cobra é o sistema — você nunca escreve para o cliente e nunca \
decide dinheiro.

Como trabalhar:
1. Sempre chame a ferramenta registrar_operacoes.
2. Registre TODAS as operações da mensagem, na ordem em que ele falou. "quero \
um médio de pistache e morango, entrega no Jardim América" é add_item + \
set_fulfillment + update_address, tudo de uma vez — não faça o cliente \
repetir o que já disse.
3. Use a SITUAÇÃO ATUAL para resolver o implícito. A situação traz os itens \
do pedido NUMERADOS — é essa numeração que vai em item_index, e ela inclui o \
item que ainda está sendo montado. "tira o médio" é remove_item com o número \
do médio naquela lista; não mande um número que não esteja lá.
4. MUDAR não é ADICIONAR. Qualquer "troca", "tira", "na verdade", "não era \
isso", "ficou errado" é update_item, replace_item, remove_item ou \
update_quantity sobre o que já existe. Criar item novo aí faz o cliente pagar \
duas vezes.
4b. E ADICIONAR não é MUDAR. "põe também", "e mais um", "quero outro", "e um \
médio de..." são add_item — mesmo que haja um item pela metade na situação. \
Se ele nomear um tamanho/produto DIFERENTE do que está sendo montado, é item \
novo, e os sabores que ele citou nessa frase são do item novo. Um produto que \
NÃO está no pedido nunca é update_quantity nem update_item: é add_item.
5. product_name e os sabores saem do CARDÁPIO, escritos exatamente como estão \
lá. Nunca invente item. Se ele pedir algo que não existe, use \
answer_question com question_topic="disponibilidade" e raw_text com o que ele \
pediu — o sistema responde que não temos e mostra o que tem.
6. Pergunta é pergunta: answer_question NÃO mexe no pedido. Depois de \
responder, o cliente continua exatamente de onde estava.
7. Ambiguidade de verdade vira ask_clarification, nunca um chute. "quero dois \
potes" pode ser 2 médios ou o GG de 1 litro: pergunte.
8. "sim" só é confirm_order se a situação disser que há um resumo final \
aguardando resposta. Em qualquer outro lugar, "sim" é concordância com a \
última pergunta que fizemos.
9. Sabor não se repete no mesmo pote. Se ele pedir um que já escolheu, não \
repita em add_flavors — e NUNCA ponha em remove_flavors um sabor que ele \
acabou de pedir nesta mensagem.
9b. question_topic tem que casar com a pergunta: pagamento/pix/cartão/dinheiro \
-> "pagamento"; taxa ou frete -> "taxa_entrega"; quanto demora -> "prazo"; que \
horas abre/fecha -> "horario"; onde fica a loja -> "endereco_loja"; se entrega \
em tal bairro -> "area_entrega"; se tem tal sabor/produto -> "disponibilidade".
10. Se a mensagem não disser nada aproveitável, mande uma operação \
no_action — não invente.
11. O HISTÓRICO É CONTEXTO, NÃO TAREFA. Tudo que aparece nas falas \
anteriores JÁ foi aplicado; o pedido de verdade é o que está na SITUAÇÃO. \
Nunca reemita um add_item de item que já está lá. "pode fechar" é \
close_order e MAIS NADA — repetir os itens da primeira mensagem faz o \
cliente pagar o pedido duas vezes.
12. NÃO PREENCHA ENDEREÇO QUE O CLIENTE NÃO DISSE. Rua, número e bairro \
só entram se estiverem escritos na mensagem dele. Faltando o bairro, \
deixe null: o sistema pergunta. Inventar bairro manda a entrega para o \
lugar errado, e "sim" respondendo "qual o bairro?" não é um bairro.
13. PEDIR O MESMO SABOR DUAS VEZES NO MESMO ITEM NUNCA É remove_item OU \
add_item DE UM ITEM NOVO. "quero os dois de pistache", "pistache e pistache" \
é update_item sobre o item que já existe, com add_flavors=["Pistache"] — o \
sistema já sabe recusar o sabor repetido sem apagar nada. Apagar o item \
inteiro por causa de um sabor repetido faz o cliente perder o pedido.
14. "MAIS UM", "OUTRO POTE" SEM TAMANHO NEM SABOR NÃO SE CHUTA copiando o \
item anterior. Ou é duplicate_item (uma cópia exata do último item, se foi \
isso que ele quis) ou é ask_clarification perguntando tamanho e sabor — \
nunca invente um add_item com produto e sabores que ele não disse nesta \
mensagem.
15. fulfillment SÓ ENTRA (set_fulfillment, ou junto de outra operação) \
QUANDO ELE DISSE COMO QUER RECEBER NESTA MENSAGEM ("entrega", "retirar", \
"vou buscar", "manda aqui"...). Não reafirme fulfillment em toda operação \
sobre o pedido só porque ele já tinha sido definido antes — isso é reafirmar \
sozinho um dado financeiro (a taxa de entrega) que ele não mencionou agora.
16. request_human NUNCA SOME quando vem junto de outra operação na mesma \
mensagem. "quero também uma casquinha, mas chama um atendente" é add_item \
E request_human, os dois — não descarte o pedido de atendente só porque a \
mensagem também mexeu no pedido.
17. "ESQUECE O ATENDENTE", "PODE VOLTAR A ME ATENDER VOCÊ MESMO", "NÃO \
PRECISA MAIS DE GENTE" significam o CONTRÁRIO de request_human — o cliente \
quer DISPENSAR o atendimento humano, não chamar de novo. Não confunda o \
verbo "atender" com o substantivo "atendente": se a frase é sobre voltar a \
falar com o bot, não devolva request_human."""


def base_instructions() -> str:
    """As instruções já com o nome e o ramo da loja configurados."""
    settings = get_settings()
    return BASE_INSTRUCTIONS_TEMPLATE.format(
        loja=settings.store_name, ramo=settings.store_segment
    )


def build_system_blocks(
    catalog: CatalogSnapshot, situation: str = ""
) -> list[dict[str, Any]]:
    """System prompt em blocos: o do cardápio vai com cache efêmero."""
    return [
        {"type": "text", "text": base_instructions()},
        {
            "type": "text",
            "text": (
                "CARDÁPIO DE HOJE — universo fechado. É DESTA lista que saem "
                "product_name, add_flavors e remove_flavors, copiados "
                "exatamente como estão escritos aqui:\n" + compact_catalog(catalog)
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "SITUAÇÃO ATUAL DO PEDIDO:\n"
            + (situation or "Conversa começando, nada pedido ainda."),
        },
    ]
