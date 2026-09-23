"""Enumerações compartilhadas por todas as camadas.

Os valores em string espelham exatamente os tipos ENUM definidos em
`back/db/schema.sql`. Mudou aqui, muda lá.
"""

from enum import StrEnum


class OrderStatus(StrEnum):
    NOVO = "novo"
    PREPARANDO = "preparando"
    ENTREGA = "entrega"
    FINALIZADO = "finalizado"
    CANCELADO = "cancelado"


class PaymentStatus(StrEnum):
    PENDENTE = "pendente"
    PAGO = "pago"
    EXPIRADO = "expirado"
    CANCELADO = "cancelado"
    REEMBOLSADO = "reembolsado"


class FulfillmentType(StrEnum):
    ENTREGA = "entrega"
    RETIRADA = "retirada"


class OrderChannel(StrEnum):
    WHATSAPP = "whatsapp"
    ADMIN = "admin"
    SIMULADOR = "simulador"


class MessageDirection(StrEnum):
    ENTRADA = "entrada"
    SAIDA = "saida"


class ConversationState(StrEnum):
    """Onde a conversa está — só o que muda o que o sistema PODE fazer.

    Eram dez estados, um para cada etapa do diálogo (saudação, escolhendo
    produto, personalizando item, revisando carrinho, coletando endereço). Na
    prática a etapa do diálogo já está nos `slots` — tem item em construção?
    o carrinho está vazio? falta endereço? — e ter as duas coisas fazia o
    agente brigar consigo mesmo: o cliente falava de sabor num estado que só
    aceitava produto e ouvia "não entendi".

    Ficaram os estados que carregam uma *garantia*, não uma etapa:

    - `CONVERSANDO`: montando o pedido. O que acontece aqui é decidido pelo
      que a IA entendeu + o que já está nos slots.
    - `CONFIRMANDO_PEDIDO`: o cliente viu o resumo com o total. É o único
      lugar de onde se pode cobrar.
    - `AGUARDANDO_PAGAMENTO`: Pix emitido; só o webhook do provedor tira daqui.
    - `CONCLUIDO` / `CANCELADO`: fim de ciclo.
    - `ATENDIMENTO_HUMANO`: o bot cala enquanto a loja atende.
    """

    CONVERSANDO = "conversando"
    CONFIRMANDO_PEDIDO = "confirmando_pedido"
    AGUARDANDO_PAGAMENTO = "aguardando_pagamento"
    CONCLUIDO = "concluido"
    ATENDIMENTO_HUMANO = "atendimento_humano"
    CANCELADO = "cancelado"


#: Estados das versões anteriores, para as conversas que já estão no banco.
#: Todos eram etapas do diálogo, e hoje o diálogo inteiro é `CONVERSANDO`.
LEGACY_STATES = {
    "saudacao": ConversationState.CONVERSANDO,
    "escolhendo_produto": ConversationState.CONVERSANDO,
    "personalizando_item": ConversationState.CONVERSANDO,
    "revisando_carrinho": ConversationState.CONVERSANDO,
    "coletando_endereco": ConversationState.CONVERSANDO,
}


def parse_state(raw: str) -> ConversationState:
    """Lê o estado do banco aceitando os nomes antigos."""
    try:
        return ConversationState(raw)
    except ValueError:
        return LEGACY_STATES.get(raw, ConversationState.CONVERSANDO)


class Intent(StrEnum):
    """Intenções que o LLM pode extrair de uma mensagem do cliente.

    Note que a intenção não decide o fluxo sozinha: a máquina de estados só
    aceita as intenções que fazem sentido no estado atual.
    """

    SAUDAR = "saudar"
    PERGUNTAR = "perguntar"
    ESCOLHER_PRODUTO = "escolher_produto"
    ESCOLHER_COMPLEMENTOS = "escolher_complementos"
    ADICIONAR_MAIS = "adicionar_mais"
    REMOVER_ITEM = "remover_item"
    FINALIZAR_PEDIDO = "finalizar_pedido"
    INFORMAR_ENDERECO = "informar_endereco"
    INFORMAR_NOME = "informar_nome"
    ESCOLHER_RETIRADA = "escolher_retirada"
    ESCOLHER_ENTREGA = "escolher_entrega"
    CONFIRMAR = "confirmar"
    NEGAR = "negar"
    CANCELAR = "cancelar"
    CONSULTAR_STATUS = "consultar_status"
    VER_CARDAPIO = "ver_cardapio"
    FALAR_COM_HUMANO = "falar_com_humano"
    DESCONHECIDO = "desconhecido"
