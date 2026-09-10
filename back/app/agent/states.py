"""Tabela de transições da máquina de estados do agente.

A tabela é declarativa de propósito: ela é a documentação executável do fluxo
de pedido e o ponto onde se garante que o agente não pule etapas (por exemplo,
gerar Pix sem endereço, ou fechar pedido com carrinho vazio).
"""

from __future__ import annotations

from app.domain.enums import ConversationState as S

# Transições permitidas. Qualquer salto fora daqui é bug e deve levantar erro.
TRANSITIONS: dict[S, set[S]] = {
    S.SAUDACAO: {
        S.ESCOLHENDO_PRODUTO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.ESCOLHENDO_PRODUTO: {
        S.PERSONALIZANDO_ITEM,
        S.REVISANDO_CARRINHO,   # produto sem grupos obrigatórios
        S.ESCOLHENDO_PRODUTO,   # não entendeu, repergunta
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.PERSONALIZANDO_ITEM: {
        S.PERSONALIZANDO_ITEM,  # ainda faltam grupos obrigatórios
        S.REVISANDO_CARRINHO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.REVISANDO_CARRINHO: {
        S.ESCOLHENDO_PRODUTO,   # "quero mais uma coisa"
        S.COLETANDO_ENDERECO,
        S.CONFIRMANDO_PEDIDO,   # retirada na loja: pula endereço
        S.REVISANDO_CARRINHO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.COLETANDO_ENDERECO: {
        S.COLETANDO_ENDERECO,   # endereço incompleto, pede o que falta
        S.CONFIRMANDO_PEDIDO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.CONFIRMANDO_PEDIDO: {
        S.AGUARDANDO_PAGAMENTO,
        S.REVISANDO_CARRINHO,   # cliente quis mudar algo
        S.CONFIRMANDO_PEDIDO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.AGUARDANDO_PAGAMENTO: {
        S.CONCLUIDO,            # webhook de pagamento aprovado
        S.AGUARDANDO_PAGAMENTO, # cliente perguntou algo enquanto paga
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,            # Pix expirou ou cliente desistiu
    },
    S.CONCLUIDO: {
        S.SAUDACAO,             # cliente volta para um novo pedido
        S.ATENDIMENTO_HUMANO,
    },
    S.ATENDIMENTO_HUMANO: {
        S.SAUDACAO,             # lojista devolve a conversa para o bot
        S.CANCELADO,
    },
    S.CANCELADO: {
        S.SAUDACAO,             # novo pedido depois de cancelar
    },
}

#: Estados em que a conversa não está mais conduzindo um pedido ativo.
TERMINAL_STATES: frozenset[S] = frozenset({S.CONCLUIDO, S.CANCELADO})

#: Estados a partir dos quais um "quero cancelar" do cliente é aceito.
CANCELLABLE_STATES: frozenset[S] = frozenset(
    {
        S.ESCOLHENDO_PRODUTO,
        S.PERSONALIZANDO_ITEM,
        S.REVISANDO_CARRINHO,
        S.COLETANDO_ENDERECO,
        S.CONFIRMANDO_PEDIDO,
        S.AGUARDANDO_PAGAMENTO,
    }
)


class InvalidTransition(RuntimeError):
    """Tentativa de pular uma etapa do fluxo."""

    def __init__(self, origin: S, destination: S) -> None:
        super().__init__(f"Transição inválida: {origin} -> {destination}")
        self.origin = origin
        self.destination = destination


def can_transition(origin: S, destination: S) -> bool:
    return destination in TRANSITIONS.get(origin, set())


def assert_transition(origin: S, destination: S) -> None:
    if not can_transition(origin, destination):
        raise InvalidTransition(origin, destination)
