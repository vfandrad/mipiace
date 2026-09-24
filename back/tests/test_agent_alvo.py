"""Em qual item a operação cai — os defeitos da rodada de 3 conversas.

Todos os erros graves daquela rodada tinham a mesma raiz: o pedido tinha DOIS
itens, um deles ainda em montagem, e a operação caía no item errado. O caso
que dói: o cliente tinha um pote grande fechado e um médio pela metade, disse
"tira o médio", e o bot removeu o pote grande e esvaziou o pedido.

A correção foi de desenho — o item em montagem passou a viver no carrinho, com
o mesmo número que o cliente vê — e estes testes existem para que ela não
regrida sozinha.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agent.machine import describe_situation, run
from app.agent.plan import Action, Operation
from app.domain.enums import FulfillmentType
from tests.test_agent_machine import build_deps, build_session, op, plano


async def _pedido_com_dois_itens(deps, session):
    """1. Pote 500ml (Pistache, Morango) — completo; 2. Pote 240ml — montando."""
    await run(
        deps,
        session,
        plano(
            op(
                Action.ADD_ITEM,
                product_name="Pote 500ml",
                add_flavors=["Pistache", "Morango"],
            )
        ),
        "um pote grande de pistache e morango",
    )
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 240ml")),
        "poe tambem um pote medio",
    )
    assert len(session.cart.items) == 2


# ---------------------------------------------------------------------------
# O alvo da operação
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tirar_o_item_em_montagem_nao_apaga_o_que_ja_estava_fechado() -> None:
    """"tira o médio" — o defeito que zerou o pedido de um cliente."""
    deps, session = build_deps(), build_session()
    await _pedido_com_dois_itens(deps, session)

    await run(
        deps,
        session,
        plano(op(Action.REMOVE_ITEM, item_index=2)),
        "pensando bem tira o medio",
    )

    assert len(session.cart.items) == 1
    item = session.cart.items[0]
    assert item.product_name == "Pote 500ml"
    assert [c.name for c in item.complements] == ["Pistache", "Morango"]


@pytest.mark.asyncio
async def test_remover_produto_que_nao_esta_no_pedido_nao_chuta_o_que_esta() -> None:
    """Nomear um produto ausente nunca pode remover o único item do pedido."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(
            op(
                Action.ADD_ITEM,
                product_name="Pote 500ml",
                add_flavors=["Pistache", "Morango"],
            )
        ),
        "pote grande de pistache e morango",
    )

    replies = await run(
        deps,
        session,
        plano(op(Action.REMOVE_ITEM, product_name="Pote 240ml")),
        "tira o medio",
    )

    assert len(session.cart.items) == 1  # o pote grande continua lá
    assert any("qual" in reply.lower() for reply in replies)


@pytest.mark.asyncio
async def test_adicionar_outro_produto_no_meio_da_montagem_cria_item_novo() -> None:
    """"põe também um médio" não pode virar sabor do pote que está aberto."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=["Pistache"])),
        "um pote grande de pistache",
    )
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 240ml", add_flavors=["Morango"])),
        "poe tambem um pote medio de morango",
    )

    assert [i.product_name for i in session.cart.items] == ["Pote 500ml", "Pote 240ml"]
    assert [c.name for c in session.cart.items[0].complements] == ["Pistache"]
    assert [c.name for c in session.cart.items[1].complements] == ["Morango"]


@pytest.mark.asyncio
async def test_quantidade_de_produto_fora_do_pedido_vira_adicao() -> None:
    """"põe 2 cascões" não pode virar "2x pote de R$ 32"."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(
            op(
                Action.ADD_ITEM,
                product_name="Pote 500ml",
                add_flavors=["Pistache", "Morango"],
            )
        ),
        "pote grande",
    )

    await run(
        deps,
        session,
        plano(op(Action.UPDATE_QUANTITY, product_name="Casquinha", quantity=2)),
        "poe 2 casquinhas tambem",
    )

    assert [i.product_name for i in session.cart.items] == ["Pote 500ml", "Casquinha"]
    assert session.cart.items[0].quantity == 1
    assert session.cart.items[1].quantity == 2
    assert session.cart.subtotal == Decimal("50.00")  # 32 + 2x9


@pytest.mark.asyncio
async def test_editar_sabor_de_item_fechado_com_outro_em_montagem() -> None:
    """Com dois itens, o índice manda: "troca no grande" mexe no grande."""
    deps, session = build_deps(), build_session()
    await _pedido_com_dois_itens(deps, session)

    await run(
        deps,
        session,
        plano(
            op(
                Action.UPDATE_ITEM,
                item_index=1,
                remove_flavors=["Morango"],
                add_flavors=["Chocolate"],
            )
        ),
        "muda o morango do grande por chocolate",
    )

    assert [c.name for c in session.cart.items[0].complements] == ["Pistache", "Chocolate"]
    assert session.cart.items[1].complements == []  # o médio não foi tocado


# ---------------------------------------------------------------------------
# O retrato que a IA recebe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_situacao_numera_o_item_em_montagem_junto_com_o_resto() -> None:
    """A IA precisa ver a MESMA lista que o cliente vê, com os mesmos números."""
    deps, session = build_deps(), build_session()
    await _pedido_com_dois_itens(deps, session)

    situacao = describe_situation(deps, session)

    assert "1. 1x Pote 500ml" in situacao
    assert "2. 1x Pote 240ml" in situacao
    assert "EM MONTAGEM" in situacao
    assert "item_index" in situacao  # diz ao modelo que a numeração é essa


# ---------------------------------------------------------------------------
# Confirmar em voz alta o que foi anotado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escolher_entrega_e_confirmado_ao_cliente() -> None:
    """"quero entrega" respondido só com o resumo do carrinho parece ignorado."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(
            op(
                Action.ADD_ITEM,
                product_name="Pote 500ml",
                add_flavors=["Pistache", "Morango"],
            )
        ),
        "pote grande",
    )

    replies = await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="entrega")),
        "quero entrega",
    )

    assert any("entrega" in reply.lower() for reply in replies)
    assert session.slots.get("fulfillment") == FulfillmentType.ENTREGA.value


@pytest.mark.asyncio
async def test_endereco_completo_e_repetido_de_volta() -> None:
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(
            op(
                Action.ADD_ITEM,
                product_name="Pote 500ml",
                add_flavors=["Pistache", "Morango"],
            )
        ),
        "pote grande",
    )

    replies = await run(
        deps,
        session,
        plano(
            Operation(
                action=Action.UPDATE_ADDRESS,
                address={"rua": "Rua das Acácias", "numero": "120", "bairro": "Centro"},
            )
        ),
        "rua das acacias 120, centro",
    )

    assert any("Acácias" in reply for reply in replies)


# ---------------------------------------------------------------------------
# Sabor que o modelo pede e tira na mesma frase
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sabor_pedido_e_removido_na_mesma_operacao_nao_some() -> None:
    """O modelo devolve em remove_flavors um sabor que o cliente acabou de pedir."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=["Morango"])),
        "pote grande de morango",
    )

    await run(
        deps,
        session,
        plano(
            op(
                Action.UPDATE_ITEM,
                item_index=1,
                add_flavors=["Morango", "Pistache"],
                remove_flavors=["Morango"],
            )
        ),
        "bota morango e pistache",
    )

    nomes = [c.name for c in session.cart.items[0].complements]
    assert nomes == ["Morango", "Pistache"]


# ---------------------------------------------------------------------------
# Os dois defeitos que a própria correção introduziu
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remover_sabor_nunca_apaga_o_item() -> None:
    """"pistache, morango e pistache" chegou como remove_item + sabor repetido.

    O item não tinha sabor nenhum ainda, a remoção não achou o sabor e o
    executor apagava o pote inteiro. Enquanto a operação só citar SABOR — sem
    número e sem nome de produto — ela não pode remover item.
    """
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml")),
        "quero um pote grande",
    )

    await run(
        deps,
        session,
        plano(op(Action.REMOVE_ITEM, remove_flavors=["Pistache"])),
        "pistache, morango e pistache",
    )

    assert len(session.cart.items) == 1
    assert session.cart.items[0].product_name == "Pote 500ml"


@pytest.mark.asyncio
async def test_sabores_respondidos_como_add_item_caem_no_item_aberto() -> None:
    """O modelo manda add_item para o que é resposta à pergunta dos sabores.

    Criar outro pote a cada resposta enchia o pedido de itens fantasma, e
    nenhum deles fechava.
    """
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml")),
        "quero um pote grande",
    )

    await run(
        deps,
        session,
        plano(
            op(
                Action.ADD_ITEM,
                product_name="Pote 500ml",
                add_flavors=["Pistache", "Morango"],
            )
        ),
        "pistache e morango",
    )

    assert len(session.cart.items) == 1
    assert [c.name for c in session.cart.items[0].complements] == ["Pistache", "Morango"]


@pytest.mark.asyncio
async def test_sabores_sem_produto_nomeado_completam_o_item_aberto() -> None:
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml")),
        "quero um pote grande",
    )

    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, add_flavors=["Pistache", "Chocolate"])),
        "pistache e chocolate",
    )

    assert len(session.cart.items) == 1
    assert [c.name for c in session.cart.items[0].complements] == ["Pistache", "Chocolate"]


@pytest.mark.asyncio
async def test_nao_repete_a_mesma_frase_no_mesmo_turno() -> None:
    """Um update_address por campo fazia o bot dizer "Endereço anotado" 3x."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(
            op(
                Action.ADD_ITEM,
                product_name="Pote 500ml",
                add_flavors=["Pistache", "Morango"],
            )
        ),
        "pote grande",
    )

    endereco = {"rua": "Rua das Acácias", "numero": "120", "bairro": "Centro"}
    replies = await run(
        deps,
        session,
        plano(
            Operation(action=Action.UPDATE_ADDRESS, address=endereco),
            Operation(action=Action.UPDATE_ADDRESS, address=endereco),
        ),
        "rua das acacias 120, centro",
    )

    assert len(replies) == len(set(replies))
