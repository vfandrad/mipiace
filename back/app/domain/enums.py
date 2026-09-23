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
    """Estados da máquina que conduz o pedido pelo WhatsApp."""

    SAUDACAO = "saudacao"
    ESCOLHENDO_PRODUTO = "escolhendo_produto"
    PERSONALIZANDO_ITEM = "personalizando_item"
    REVISANDO_CARRINHO = "revisando_carrinho"
    COLETANDO_ENDERECO = "coletando_endereco"
    CONFIRMANDO_PEDIDO = "confirmando_pedido"
    AGUARDANDO_PAGAMENTO = "aguardando_pagamento"
    CONCLUIDO = "concluido"
    ATENDIMENTO_HUMANO = "atendimento_humano"
    CANCELADO = "cancelado"


class Intent(StrEnum):
    """Intenções que o LLM pode extrair de uma mensagem do cliente.

    Note que a intenção não decide o fluxo sozinha: a máquina de estados só
    aceita as intenções que fazem sentido no estado atual.
    """

    SAUDAR = "saudar"
    ESCOLHER_PRODUTO = "escolher_produto"
    ESCOLHER_COMPLEMENTOS = "escolher_complementos"
    ADICIONAR_MAIS = "adicionar_mais"
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
