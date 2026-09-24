"""As frases que um cliente de verdade escreve.

Este arquivo existe por causa de um atendimento real que terminou em
atendimento humano sem montar pedido nenhum: "quero um pote G" e "pote grande"
não casavam com nada, porque o nome do produto no cardápio é o tamanho
("G - 500ml") e o resolvedor só olhava o nome. O resto da suíte não pegava isso
— ela roda com o LLM falso, que entende essas frases por regra própria.

A regra daqui: tudo é testado contra o `resolver` e o `keywords`, sem LLM
nenhum no meio. Se uma frase dessas parar de casar, é regressão.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.resolver import MatchStatus, resolve_complement, resolve_product
from app.domain.catalog import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
)


def build_cardapio() -> CatalogSnapshot:
    """O cardápio da Mi Piace como ele é: o nome é o tamanho."""

    def pote(nome: str, descricao: str, preco: str, sabores: int) -> CatalogProduct:
        product_id = uuid4()
        group_id = uuid4()
        return CatalogProduct(
            id=product_id,
            name=nome,
            description=descricao,
            base_price=Decimal(preco),
            groups=[
                CatalogGroup(
                    id=group_id,
                    name=f"Escolha {sabores} sabores",
                    min_choices=sabores,
                    max_choices=sabores,
                    is_required=True,
                    complements=[
                        CatalogComplement(id=uuid4(), group_id=group_id, name=nome_sabor)
                        for nome_sabor in (
                            "Pistache",
                            "Morango",
                            "Limão siciliano",
                            "Chocolate",
                            "Fior di latte",
                        )
                    ],
                )
            ],
        )

    return CatalogSnapshot(
        products=[
            CatalogProduct(
                id=uuid4(), name="Cascão", description=None, base_price=Decimal("3.00")
            ),
            pote("M - 240ml", "Pote médio: escolha 2 sabores", "30.00", 2),
            pote("G - 500ml", "Pote grande: escolha 3 sabores", "50.00", 3),
            pote("GG - 1000ml", "Dois potes G: escolha 6 sabores", "90.00", 6),
        ]
    )


@pytest.fixture
def cardapio() -> CatalogSnapshot:
    return build_cardapio()


@pytest.mark.parametrize(
    "frase, esperado",
    [
        ("quero um pote G", "G - 500ml"),
        ("pote grande", "G - 500ml"),
        ("quero o pote grande", "G - 500ml"),
        ("g", "G - 500ml"),
        ("G - 500ml", "G - 500ml"),
        ("500ml", "G - 500ml"),
        ("quero um pote M", "M - 240ml"),
        ("pote medio", "M - 240ml"),
        ("gg", "GG - 1000ml"),
        ("quero o gg", "GG - 1000ml"),
        ("cascao", "Cascão"),
    ],
)
def test_cliente_pede_pelo_tamanho(cardapio, frase, esperado) -> None:
    match = resolve_product(frase, cardapio)
    assert match.ok, f"{frase!r} não casou: {match.status}"
    assert match.product is not None and match.product.name == esperado


def test_pote_sozinho_pergunta_qual(cardapio) -> None:
    """Ambíguo é para perguntar, não para chutar nem para "não entendi"."""
    match = resolve_product("quero um pote", cardapio)
    assert match.status is MatchStatus.AMBIGUOUS
    assert len(match.candidates) > 1


def test_coisa_que_nao_existe_continua_nao_existindo(cardapio) -> None:
    """A abertura para descrição não pode virar porta para inventar item."""
    for frase in ("quero uma pizza", "tem açaí?", "milkshake de ovomaltine"):
        assert resolve_product(frase, cardapio).status is MatchStatus.NOT_FOUND


def test_sabores_pelo_nome(cardapio) -> None:
    grupo = cardapio.product_by_name("G - 500ml").groups[0]
    for frase, esperado in [
        ("pistache", "Pistache"),
        ("limao", "Limão siciliano"),
        ("quero morango", "Morango"),
    ]:
        match = resolve_complement(frase, grupo)
        assert match.ok, f"{frase!r} não casou: {match.status}"
        assert match.complement is not None and match.complement.name == esperado


@pytest.mark.parametrize("frase", ["quero dois potes", "quero 2 potes", "um pote"])
def test_quantidade_sem_tamanho_pergunta_em_vez_de_chutar(cardapio, frase) -> None:
    """Regressão do teste com cliente simulado.

    "oi quero dois potes" casava com a descrição do GG ("Dois potes G") e o
    cliente que queria dois potes médios recebia, sem ser perguntado, um pote
    de R$ 90. Quantidade sem tamanho tem que virar pergunta.
    """
    match = resolve_product(frase, cardapio)
    assert match.status is MatchStatus.AMBIGUOUS
    assert len(match.candidates) >= 3
