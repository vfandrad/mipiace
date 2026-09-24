"""Eval offline: o plano esperado produz o pedido certo?

Roda sempre, sem rede e sem token. Para cada caso de `eval_cases.py`, alimenta
o executor com o plano que a IA *deveria* ter devolvido e confere o efeito no
pedido.

O que este teste prova, e o que não prova
-----------------------------------------
Prova que o contrato está fechado dos dois lados: se o modelo devolver aquelas
operações, o pedido termina como o cliente quis. É o que impede uma mudança no
executor de quebrar um fluxo em silêncio.

**Não prova que o modelo devolve aquelas operações.** Essa pergunta é do
`test_agent_eval_live.py`, que chama a OpenAI de verdade. Os dois leem a mesma
lista de casos de propósito: é uma lista só, para não existirem duas verdades
sobre o que o agente deveria fazer.
"""

from __future__ import annotations

import pytest

from app.agent.machine import run
from app.agent.plan import AgentPlan
from tests.eval_cases import CASES, EvalCase
from tests.test_agent_machine import build_deps, build_session


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", CASES, ids=lambda c: c.id)
async def test_o_plano_esperado_produz_o_pedido_certo(caso: EvalCase) -> None:
    deps = build_deps()
    session = build_session()

    if caso.preparar is not None:
        await caso.preparar(deps, session)

    replies = await run(
        deps,
        session,
        AgentPlan(operations=caso.plano_esperado(), confidence=0.9),
        caso.mensagem,
    )

    # O bot nunca pode emudecer: ficar sem resposta foi o defeito mais caro do
    # agente, porque o cliente do WhatsApp não tem a quem recorrer.
    assert replies, f"{caso.id}: o agente não respondeu nada"

    if caso.verificar is not None:
        caso.verificar(deps, session, replies)


def test_todo_caso_tem_um_porque() -> None:
    """Caso sem motivo escrito vira ruído na próxima vez que alguém mexer aqui."""
    sem_motivo = [c.id for c in CASES if not c.porque]
    assert not sem_motivo, f"casos sem `porque`: {sem_motivo}"


def test_os_ids_sao_unicos() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)), "id repetido esconde um caso do relatório"
