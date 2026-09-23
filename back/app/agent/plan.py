"""O contrato entre a IA e o sistema: operações, não um rótulo.

Antes a IA devolvia uma intenção só (`escolher_produto`) e a máquina de
estados tentava adivinhar o resto a partir do estado em que a conversa
estava. Isso produzia os piores defeitos do agente:

- "troca chocolate por fior di latte" virava um item NOVO, porque a única
  operação que existia era adicionar;
- "remove o item 1" também virava um item novo — e cada tentativa de corrigir
  o pedido aumentava a conta;
- "quero um médio de pistache e morango, entrega no Jardim América" exigia
  três turnos, porque só cabia uma intenção por mensagem.

Agora a IA traduz a mensagem em uma **lista de operações** — o que ela
entendeu que o cliente quer fazer — e o backend valida cada uma contra o
catálogo real e aplica ao estado. A IA nunca inventa produto, preço, taxa ou
disponibilidade, e nunca cobra: ela descreve a intenção, o sistema decide se
aquilo é possível.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Action(StrEnum):
    """O que o cliente está tentando fazer.

    Cada uma é uma operação sobre o pedido, independente do ponto da conversa
    em que ela chega. É isso que permite ao cliente perguntar o horário no meio
    da escolha de sabores sem perder o pedido.
    """

    ADD_ITEM = "add_item"                 # põe um item novo no pedido
    UPDATE_ITEM = "update_item"           # mexe num item que já existe
    REPLACE_ITEM = "replace_item"         # troca o produto do item, mantendo o resto
    REMOVE_ITEM = "remove_item"           # tira um item do pedido
    UPDATE_QUANTITY = "update_quantity"   # "na verdade só um", "coloca mais dois"
    DUPLICATE_ITEM = "duplicate_item"     # "quero outro igual"
    SET_FULFILLMENT = "set_fulfillment"   # entrega ou retirada
    UPDATE_ADDRESS = "update_address"     # endereço, inteiro ou aos pedaços
    SHOW_MENU = "show_menu"
    SHOW_CART = "show_cart"
    SHOW_TOTAL = "show_total"
    ANSWER_QUESTION = "answer_question"   # pergunta informativa; não mexe no pedido
    CLOSE_ORDER = "close_order"           # "pode fechar", "é só isso"
    CONFIRM_ORDER = "confirm_order"       # "sim" ao resumo final — só isso gera Pix
    CANCEL_ORDER = "cancel_order"
    REQUEST_HUMAN = "request_human"
    ASK_CLARIFICATION = "ask_clarification"  # a IA viu ambiguidade e NÃO escolheu
    NO_ACTION = "no_action"               # cumprimento, agradecimento, conversa fiada


#: Assuntos de pergunta que o sistema sabe responder com dado de verdade.
QUESTION_TOPICS = (
    "preco",
    "pagamento",
    "taxa_entrega",
    "area_entrega",
    "prazo",
    "horario",
    "endereco_loja",
    "restricao",
    "disponibilidade",
    "outro",
)


class Address(BaseModel):
    """Endereço como objeto, para o cliente completar em qualquer ordem."""

    rua: str | None = None
    numero: str | None = None
    bairro: str | None = None
    complemento: str | None = None
    referencia: str | None = None

    @property
    def is_complete(self) -> bool:
        return bool(self.rua and self.numero and self.bairro)


class Operation(BaseModel):
    """Uma coisa que o cliente quer fazer com o pedido.

    Os campos são todos opcionais porque cada ação usa os seus. O que nunca
    muda: `product_name` e os sabores são NOMES DO CARDÁPIO, validados pelo
    backend antes de qualquer coisa acontecer.
    """

    action: Action = Action.NO_ACTION

    #: Qual item do pedido a operação atinge (1 = o primeiro da lista mostrada).
    #: Sem índice, vale o item em construção; sem ele, o último do carrinho.
    item_index: int | None = None

    #: Nome exato do produto no cardápio.
    product_name: str | None = None
    quantity: int | None = None

    #: Sabores a acrescentar e a tirar — é o que torna "troca X por Y" uma
    #: edição do mesmo item, e não um item novo.
    add_flavors: list[str] = Field(default_factory=list)
    remove_flavors: list[str] = Field(default_factory=list)

    fulfillment: str | None = None          # "entrega" | "retirada"
    address: Address | None = None

    question_topic: str | None = None
    #: A pergunta do cliente, nas palavras dele — para o sistema responder o
    #: que ele perguntou, e não um texto genérico.
    question_text: str | None = None

    #: O que o cliente citou e o sistema não achou; vira "não temos açaí".
    raw_text: str | None = None

    #: Quando a IA viu duas leituras possíveis, o que precisa ser esclarecido.
    clarification: str | None = None


class AgentPlan(BaseModel):
    """Tudo que a IA entendeu de uma mensagem.

    Uma mensagem pode conter várias operações ("tira o primeiro, põe um grande
    de chocolate e quero entrega") — e o cliente não deveria precisar de três
    turnos para dizer isso.
    """

    operations: list[Operation] = Field(default_factory=list)
    confidence: float = 0.0
    customer_name: str | None = None

    # Metadados de auditoria/custo (gravados em conversation_messages).
    model: str | None = None
    usage: dict | None = None

    @property
    def actions(self) -> list[Action]:
        return [op.action for op in self.operations]

    def first(self, action: Action) -> Operation | None:
        return next((op for op in self.operations if op.action is action), None)

    def has(self, action: Action) -> bool:
        return any(op.action is action for op in self.operations)
