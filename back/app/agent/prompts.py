"""Prompts e schema da tool usada para arrancar saída estruturada do modelo.

O cardápio entra no system prompt em um bloco próprio com `cache_control`
efêmero: ele é grande, é idêntico entre turnos e muda raramente, então é
exatamente o tipo de conteúdo que o prompt caching do provedor desconta.
"""

from __future__ import annotations

from typing import Any

from app.domain.catalog import CatalogSnapshot
from app.domain.enums import ConversationState, Intent

#: Nome da tool. O modelo é forçado a chamá-la (tool_choice), então ela é o
#: único formato de saída possível — não há texto livre para parsear.
TOOL_NAME = "registrar_interpretacao"

_INTENT_DESCRIPTIONS = {
    Intent.SAUDAR: "cumprimento, início de conversa",
    Intent.ESCOLHER_PRODUTO: "cliente indicou um item do cardápio",
    Intent.ESCOLHER_COMPLEMENTOS: "cliente indicou sabores/adicionais",
    Intent.ADICIONAR_MAIS: "cliente quer acrescentar outro item",
    Intent.REMOVER_ITEM: (
        "cliente quer TIRAR algo que já está no pedido, ou reclama que ficou "
        "errado/duplicado: 'tira o segundo', 'remove o item 1', 'quero só um "
        "pote', 'esse não era pra estar aí'. NUNCA use escolher_produto aqui"
    ),
    Intent.FINALIZAR_PEDIDO: "cliente quer fechar o pedido",
    Intent.INFORMAR_ENDERECO: "cliente informou endereço de entrega",
    Intent.INFORMAR_NOME: "cliente informou o próprio nome",
    Intent.ESCOLHER_RETIRADA: "cliente vai retirar na loja",
    Intent.ESCOLHER_ENTREGA: "cliente quer receber em casa, por entrega",
    Intent.CONFIRMAR: "sim, pode ser, confirmo",
    Intent.NEGAR: "não, nada disso",
    Intent.CANCELAR: "cliente quer cancelar o pedido",
    Intent.CONSULTAR_STATUS: "cliente pergunta sobre um pedido já feito",
    Intent.VER_CARDAPIO: "cliente quer ver as opções",
    Intent.FALAR_COM_HUMANO: "cliente quer falar com uma pessoa",
    Intent.DESCONHECIDO: "não deu para entender",
}


def tool_schema() -> dict[str, Any]:
    """input_schema espelhando `NluResult` — o modelo só preenche estes campos."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Registra a interpretação da mensagem do cliente. "
            "Use SEMPRE esta ferramenta, nunca responda em texto livre."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [i.value for i in Intent],
                    "description": "\n".join(
                        f"{intent.value}: {desc}"
                        for intent, desc in _INTENT_DESCRIPTIONS.items()
                    ),
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Quão certo você está da intenção.",
                },
                "product_query": {
                    "type": ["string", "null"],
                    "description": (
                        "Trecho LITERAL da mensagem que nomeia o produto. "
                        "Não normalize, não traduza, não invente id."
                    ),
                },
                "complement_queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Trechos literais que nomeiam sabores/adicionais, "
                        "um por escolha."
                    ),
                },
                "product_name": {
                    "type": ["string", "null"],
                    "description": (
                        "OBRIGATÓRIO sempre que a mensagem indicar um item do "
                        "cardápio: o NOME EXATO do item, copiado tal como está "
                        "escrito na lista do cardápio (ex.: \"G - 500ml\"). "
                        "Use tamanho, volume e descrição para casar: "
                        "\"pote G\", \"pote grande\", \"o de 500ml\" e \"o maior\" "
                        "são todos itens do cardápio. Só deixe nulo se a "
                        "mensagem não falar de item nenhum ou se houver empate "
                        "real entre dois itens."
                    ),
                },
                "complement_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Nomes EXATOS de sabores/adicionais do cardápio que o "
                        "cliente escolheu, na ordem em que apareceram."
                    ),
                },
                "quantity": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "description": "Quantidade pedida, se o cliente disse.",
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
                    "additionalProperties": False,
                },
                "customer_name": {"type": ["string", "null"]},
                "fulfillment": {
                    "type": ["string", "null"],
                    "enum": ["entrega", "retirada", None],
                    "description": (
                        "Preencha SEMPRE que a mensagem disser como o cliente "
                        "quer receber, mesmo de passagem e mesmo que a "
                        "intenção principal seja outra: \"quero um pote G, vou "
                        "buscar aí\" -> intent=escolher_produto e "
                        "fulfillment=\"retirada\"."
                    ),
                },
            },
            # product_name entra como obrigatório (aceitando null) de propósito:
            # sem isso o gpt-4o-mini simplesmente ignorava o campo e "quero um
            # pote G" voltava só com o trecho literal, que não casa com nome
            # nenhum do cardápio.
            "required": ["intent", "confidence", "product_name"],
            "additionalProperties": False,
        },
    }


def compact_catalog(catalog: CatalogSnapshot) -> str:
    """Cardápio em texto enxuto — é o universo fechado do modelo."""
    lines: list[str] = []
    for product in catalog.available_products:
        # A descrição ("Pote grande: escolha 3 sabores") é o que liga o jeito
        # como o cliente fala ao nome do item ("G - 500ml"). Sem ela no prompt,
        # o modelo não tem como preencher product_name.
        descricao = f" — {product.description}" if product.description else ""
        lines.append(f"- {product.name}{descricao}")
        for group in product.groups:
            names = ", ".join(c.name for c in group.available_complements)
            if not names:
                continue
            regra = f"escolhe {group.min_choices}-{group.max_choices}"
            lines.append(f"    [{group.name} | {regra}]: {names}")
    return "\n".join(lines) or "(cardápio vazio)"


_STATE_HINTS = {
    ConversationState.SAUDACAO: "A conversa está começando.",
    ConversationState.ESCOLHENDO_PRODUTO: (
        "O cliente está escolhendo o produto. Espere nome de produto ou número."
    ),
    ConversationState.PERSONALIZANDO_ITEM: (
        "O cliente está escolhendo sabores/adicionais. "
        "Prefira 'escolher_complementos' e preencha complement_queries."
    ),
    ConversationState.REVISANDO_CARRINHO: (
        "O carrinho está montado. Espere 'quero mais', 'fechar', cancelamento "
        "— ou, se já perguntamos como o cliente quer receber, a resposta "
        "'entrega'/'retirada' ('vou buscar', 'retiro aí' = escolher_retirada)."
    ),
    ConversationState.COLETANDO_ENDERECO: (
        "Estamos pedindo o endereço. Preencha o objeto address com o que vier, "
        "mesmo que parcial."
    ),
    ConversationState.CONFIRMANDO_PEDIDO: (
        "Pedimos a confirmação final. Espere confirmar/negar."
    ),
    ConversationState.AGUARDANDO_PAGAMENTO: (
        "O Pix já foi enviado. Espere dúvida sobre pagamento ou status."
    ),
    ConversationState.CONCLUIDO: "O pedido anterior terminou.",
    ConversationState.ATENDIMENTO_HUMANO: "A conversa está com um atendente.",
    ConversationState.CANCELADO: "O pedido anterior foi cancelado.",
}

BASE_INSTRUCTIONS = """Você é o interpretador de mensagens de uma gelateria \
brasileira (Mi Piace) que atende pelo WhatsApp.

Sua função é três coisas, e só elas: classificar a intenção da mensagem, copiar \
dela os trechos que nomeiam o que o cliente quer, e dizer a QUAL item do \
cardápio esses trechos correspondem. Você NÃO conversa, NÃO responde ao \
cliente, NÃO calcula preço, NÃO inventa pedido e NÃO decide o próximo passo.

Regras absolutas:
1. Sempre chame a ferramenta registrar_interpretacao.
2. product_query e complement_queries devem ser TRECHOS DA MENSAGEM DO CLIENTE. \
Se o cliente citar algo que não existe no cardápio abaixo, copie o trecho mesmo \
assim — quem decide se existe é o sistema, não você. NUNCA invente trecho que o \
cliente não escreveu.
3. product_name e complement_names são o contrário: aí vai o NOME EXATO como \
está escrito no cardápio, quando der para saber a qual item o cliente se \
referiu. "quero um pote grande" -> product_query="pote grande" e \
product_name="G - 500ml" (se for esse o nome no cardápio). Use a descrição e o \
tamanho para casar. Na dúvida entre dois itens, deixe nulo: o sistema pergunta.
4. Se a mensagem não fala de produto nenhum — por exemplo "fechar", "vou \
retirar na loja", "quanto ficou" — deixe product_query E product_name nulos. \
Não repesque item de mensagem anterior.
5. Se não entender, use intent="desconhecido" com confidence baixa.
6. O cliente escreve em português informal, com erros de digitação e sem acento."""


def build_system_blocks(
    state: ConversationState, catalog: CatalogSnapshot
) -> list[dict[str, Any]]:
    """System prompt em blocos: o do cardápio vai com cache efêmero."""
    return [
        {"type": "text", "text": BASE_INSTRUCTIONS},
        {
            "type": "text",
            "text": (
                "CARDÁPIO ATUAL — universo fechado. É DESTA lista que saem "
                "product_name e complement_names, copiados exatamente como "
                "estão escritos aqui:\n"
                + compact_catalog(catalog)
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                f"ESTADO ATUAL DO ATENDIMENTO: {state.value}\n"
                + _STATE_HINTS.get(state, "")
            ),
        },
    ]
