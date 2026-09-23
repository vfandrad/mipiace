"""Tabela de transições da máquina de estados do agente.

A tabela ficou pequena de propósito. Ela não descreve mais a etapa do diálogo
— isso mora nos `slots` e quem lê é a IA — e sim as poucas passagens que
precisam de garantia:

    CONVERSANDO ──► CONFIRMANDO_PEDIDO ──► AGUARDANDO_PAGAMENTO ──► CONCLUIDO

A única que realmente importa é a do meio: **não se cobra ninguém sem o
cliente ter visto o resumo com o total e concordado**. Pular etapa aqui
levanta `InvalidTransition` em vez de gerar um Pix furado.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.enums import ConversationState as S

if TYPE_CHECKING:  # evita ciclo de import em tempo de execução
    from app.agent.session import ConversationSession

TRANSITIONS: dict[S, set[S]] = {
    S.CONVERSANDO: {
        S.CONVERSANDO,          # o diálogo inteiro acontece aqui
        S.CONFIRMANDO_PEDIDO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.CONFIRMANDO_PEDIDO: {
        S.AGUARDANDO_PAGAMENTO,  # único caminho para a cobrança
        S.CONVERSANDO,           # cliente quis mudar algo
        S.CONFIRMANDO_PEDIDO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.AGUARDANDO_PAGAMENTO: {
        S.CONCLUIDO,             # webhook de pagamento aprovado
        S.AGUARDANDO_PAGAMENTO,  # cliente perguntou algo enquanto paga
        S.CONVERSANDO,           # desistiu do Pix e voltou a montar o pedido
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,             # Pix expirou ou cliente desistiu
    },
    S.CONCLUIDO: {
        S.CONVERSANDO,           # cliente volta para um novo pedido
        S.ATENDIMENTO_HUMANO,
    },
    S.ATENDIMENTO_HUMANO: {
        S.CONVERSANDO,           # lojista devolve, ou ninguém respondeu a tempo
        S.CANCELADO,
    },
    S.CANCELADO: {
        S.CONVERSANDO,           # novo pedido depois de cancelar
    },
}

#: Estados a partir dos quais um "quero cancelar" do cliente é aceito.
CANCELLABLE_STATES: frozenset[S] = frozenset(
    {S.CONVERSANDO, S.CONFIRMANDO_PEDIDO, S.AGUARDANDO_PAGAMENTO}
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


#: Estados que aceitam "entrar de novo" no mesmo estado — repetir a pergunta é
#: parte do fluxo neles. Nos demais, mandar para o estado atual é ruído.
_REENTERABLE: frozenset[S] = frozenset(
    {S.CONVERSANDO, S.CONFIRMANDO_PEDIDO, S.AGUARDANDO_PAGAMENTO}
)


def advance(session: "ConversationSession", destination: S) -> None:
    """Única porta de mudança de estado — valida contra a tabela de transições."""
    if session.state == destination and destination not in _REENTERABLE:
        return
    assert_transition(session.state, destination)
    session.state = destination
