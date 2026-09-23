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
from tests.test_agent_phrases import build_cardapio

TAXA = Decimal("5.00")


@pytest.fixture
def cardapio():
    return build_cardapio()


def test_pagamento_e_so_pix(cardapio) -> None:
    resposta = answer("vcs aceitam cartao?", cardapio, TAXA)
    assert resposta and "Pix" in resposta


def test_taxa_de_entrega_sai_da_configuracao(cardapio) -> None:
    resposta = answer("quanto fica a entrega?", cardapio, TAXA)
    assert resposta and "5,00" in resposta


def test_horario_admite_que_nao_sabe(cardapio) -> None:
    """Inventar horário de loja é pior do que dizer que não sabe."""
    resposta = answer("voces abrem que horas?", cardapio, TAXA)
    assert resposta and "atendente" in resposta


def test_pedido_nao_vira_faq(cardapio) -> None:
    """"quero entrega" é escolha, não pergunta — não pode virar resposta de FAQ."""
    assert answer("quero entrega", cardapio, TAXA) is None
    assert answer("retirada", cardapio, TAXA) is None
    assert answer("quero um pote grande", cardapio, TAXA) is None


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

    resposta = answer("tem sorvete sem acucar?", catalogo, TAXA)
    assert resposta and "Chocolate sem açúcar" in resposta
