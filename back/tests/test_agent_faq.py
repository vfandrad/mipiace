"""As perguntas que não são pedido.

Quatro dos dez clientes simulados perguntaram coisas triviais — cartão, taxa
de entrega, sabor sem açúcar, horário — e as quatro ouviram "não entendi"; uma
delas foi parar no atendimento humano por causa disso. A regra destes testes:
o agente só pode responder o que o sistema sabe de verdade.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agent.faq import answer
from app.core.config import get_settings
from tests.test_agent_phrases import build_cardapio

TAXA = Decimal("5.00")


@pytest.fixture
def cardapio():
    return build_cardapio()


def test_pagamento_e_so_pix(cardapio) -> None:
    resposta = answer(topic="pagamento", question="vcs aceitam cartao?", raw_text=None, catalog=cardapio, settings=get_settings())
    assert resposta and "Pix" in resposta


def test_taxa_de_entrega_sai_da_configuracao(cardapio) -> None:
    resposta = answer(topic="taxa_entrega", question="quanto fica a entrega?", raw_text=None, catalog=cardapio, settings=get_settings())
    assert resposta and "5,00" in resposta


def test_horario_admite_que_nao_sabe(cardapio) -> None:
    """Inventar horário de loja é pior do que dizer que não sabe."""
    resposta = answer(topic="horario", question="voces abrem que horas?", raw_text=None, catalog=cardapio, settings=get_settings())
    assert resposta and "time" in resposta


def test_preco_sai_do_catalogo(cardapio) -> None:
    """A IA interpreta a pergunta; o valor vem do cardápio, sempre."""
    resposta = answer(
        topic="preco",
        question="quanto custa o maior?",
        raw_text=None,
        catalog=cardapio,
        settings=get_settings(),
    )
    assert resposta and "R$ 90,00" in resposta


def test_sem_acucar_procura_no_cardapio_do_dia() -> None:
    """A resposta tem que vir do catálogo: os sabores mudam todo dia."""
    from uuid import uuid4

    from app.domain.catalog import (
        CatalogComplement,
        CatalogGroup,
        CatalogProduct,
        CatalogSnapshot,
    )

    produto_id, grupo_id = uuid4(), uuid4()
    catalogo = CatalogSnapshot(
        products=[
            CatalogProduct(
                id=produto_id,
                name="G - 500ml",
                base_price=Decimal("50.00"),
                groups=[
                    CatalogGroup(
                        id=grupo_id,
                        product_id=produto_id,
                        name="Escolha 3 sabores",
                        min_choices=3,
                        max_choices=3,
                        complements=[
                            CatalogComplement(id=uuid4(), group_id=grupo_id, name="Morango"),
                            CatalogComplement(
                                id=uuid4(), group_id=grupo_id, name="Chocolate sem açúcar"
                            ),
                        ],
                    )
                ],
            )
        ]
    )

    resposta = answer(
        topic="restricao",
        question="tem sorvete sem acucar?",
        raw_text="sem açúcar",
        catalog=catalogo,
        settings=get_settings(),
    )
    assert resposta and "Chocolate sem açúcar" in resposta
