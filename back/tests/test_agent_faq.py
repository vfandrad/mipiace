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


# ---------------------------------------------------------------------------
# O tópico da IA é palpite; o texto do cliente é prova
# ---------------------------------------------------------------------------

def test_pergunta_de_pagamento_com_topico_errado_ainda_responde_pix(cardapio) -> None:
    """O gpt-4o-mini etiquetou "qual a forma de pagamento?" como `horario`.

    O cliente ouviu "não sei responder" sobre a única forma de pagamento que o
    sistema tem. Quando o texto diz do que se trata, é o texto que manda.
    """
    resposta = answer(
        topic="horario",
        question="qual a forma de pagamento?",
        raw_text=None,
        catalog=cardapio,
        settings=get_settings(),
    )
    assert "Pix" in resposta


def test_cartao_recebe_resposta_de_verdade(cardapio) -> None:
    resposta = answer(
        topic="outro",
        question="aceitam cartao?",
        raw_text="aceitam cartao?",
        catalog=cardapio,
        settings=get_settings(),
    )
    assert "Pix" in resposta
    assert "não sei responder" not in resposta


def test_horario_configurado_e_respondido(cardapio) -> None:
    """Configurado pelo lojista, o agente responde; vazio, admite que não sabe."""

    class _Loja:
        delivery_fee = TAXA
        store_hours = "todo dia, das 14h às 22h"
        store_address = None
        store_delivery_area = None
        store_delivery_estimate = None

    resposta = answer(
        topic="horario",
        question="que horas vcs fecham?",
        raw_text=None,
        catalog=cardapio,
        settings=_Loja(),
    )
    assert "14h às 22h" in resposta


def test_pergunta_por_categoria_de_sabor_lista_a_categoria() -> None:
    """"tem sabor sem lactose?" não casa com nome de sabor nenhum.

    Quem responde é a CATEGORIA do sabor — a mesma que o lojista cadastra no
    painel e que agrupa o cardápio que o agente manda.
    """
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
                        name="Escolha 3 sabores",
                        min_choices=3,
                        max_choices=3,
                        complements=[
                            CatalogComplement(
                                id=uuid4(),
                                group_id=grupo_id,
                                name="Morango",
                                category="Sem lactose",
                            ),
                            CatalogComplement(
                                id=uuid4(),
                                group_id=grupo_id,
                                name="Chocolate",
                                category="Com lactose",
                            ),
                        ],
                    )
                ],
            )
        ]
    )

    resposta = answer(
        topic="disponibilidade",
        question="tem sabor sem lactose?",
        raw_text="sem lactose",
        catalog=catalogo,
        settings=get_settings(),
    )
    assert "Morango" in resposta
    assert "Chocolate" not in resposta
