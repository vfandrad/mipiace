"""Eval ao vivo: o modelo real entende mesmo o que o cliente disse?

    pytest -m eval

Fica **fora da execução padrão** (`addopts = -m 'not eval'` no pyproject):
chama a OpenAI, gasta token e depende de rede. Precisa de `OPENAI_API_KEY` e de
`FAKE_MODE=false`; sem isso os casos são pulados com o motivo explícito.

É este arquivo que cobre `prompts.py` e `llm_openai.py`, que antes não tinham
uma linha de teste — e é a única forma honesta de responder se o agente
generaliza. Os testes do executor provam que `UPDATE_ITEM` edita o item certo;
só este prova que **"troca o morango por chocolate" vira um UPDATE_ITEM**.

O que ele mede
--------------
Para cada caso de `eval_cases.py`: manda a mensagem com a situação real do
pedido e confere que a ação principal que voltou está entre as aceitas. Não
compara o plano inteiro campo a campo de propósito — o modelo tem liberdade
legítima de expressar a mesma intenção de mais de um jeito, e reprovar isso
mediria conformidade, não entendimento. O que o código não pode tolerar
(produto inventado, sabor repetido, cobrança sem confirmação) já é barrado pelo
executor e tem teste próprio.

Falha aqui não é necessariamente bug de código: costuma ser o prompt. O jeito
de consertar é mexer em `prompts.py` e rodar de novo — e é exatamente por isso
que a lista de casos vive separada dos dois testes que a leem.
"""

from __future__ import annotations

from importlib.util import find_spec

import pytest

from app.agent.llm_openai import OpenAILLMClient
from app.agent.machine import describe_situation
from app.agent.plan import Action
from app.core.config import get_settings
from tests.eval_cases import CASES, EvalCase
from tests.test_agent_machine import build_deps, build_session

pytestmark = pytest.mark.eval


def _motivo_para_pular() -> str | None:
    """Lê as `Settings`, e não `os.environ`: a chave costuma vir do `.env`."""
    settings = get_settings()
    if find_spec("openai") is None:
        # O SDK é importado tarde e a falha vira "plano vazio" lá dentro, o que
        # apareceria aqui como 19 casos reprovados em vez de "faltou instalar".
        return "SDK da OpenAI ausente (pip install openai)"
    if not settings.openai_api_key:
        return "OPENAI_API_KEY não configurada (.env ou ambiente)"
    if settings.fake_mode:
        return "FAKE_MODE=true: o LLM falso não mede nada sobre o prompt"
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", CASES, ids=lambda c: c.id)
async def test_o_modelo_entende_a_fala_do_cliente(caso: EvalCase) -> None:
    motivo = _motivo_para_pular()
    if motivo:
        pytest.skip(motivo)

    deps = build_deps()
    session = build_session()
    if caso.preparar is not None:
        await caso.preparar(deps, session)

    plan = await OpenAILLMClient().interpret(
        catalog=deps.catalog,
        history=[],
        message=caso.mensagem,
        # A mesma situação que o agente monta em produção: é ela que resolve
        # "esse mesmo", "o primeiro" e "isso" sem o cliente repetir nada.
        situation=describe_situation(deps, session),
    )

    assert plan.operations, (
        f"{caso.id}: o modelo não devolveu operação nenhuma para "
        f"{caso.mensagem!r} — provável falha de tool call"
    )

    voltaram = set(plan.actions)
    aceitas = caso.acoes_aceitas()
    assert voltaram & aceitas, (
        f"{caso.id}: esperava {sorted(a.value for a in aceitas)}, "
        f"veio {sorted(a.value for a in voltaram)}.\n"
        f"  mensagem: {caso.mensagem!r}\n"
        f"  por que importa: {caso.porque}"
    )


@pytest.mark.asyncio
async def test_o_modelo_nao_inventa_produto() -> None:
    """Grounding: o que ele nomeia tem de existir no cardápio.

    Vale para todos os casos de uma vez porque é uma invariante, não um
    comportamento — não há fala do cliente que justifique um produto inventado.
    """
    motivo = _motivo_para_pular()
    if motivo:
        pytest.skip(motivo)

    deps = build_deps()
    session = build_session()
    plan = await OpenAILLMClient().interpret(
        catalog=deps.catalog,
        history=[],
        message="me vê um pote gigante de flocos com granulado",
        situation=describe_situation(deps, session),
    )

    for operation in plan.operations:
        if operation.action is Action.ADD_ITEM and operation.product_name:
            assert deps.catalog.product_by_name(operation.product_name) is not None, (
                f"produto inventado: {operation.product_name!r}"
            )
