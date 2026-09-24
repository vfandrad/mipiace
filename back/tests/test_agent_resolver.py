"""Testes do guardrail de grounding.

O que se quer provar aqui: o resolvedor nunca devolve item fora do catálogo,
distingue "não achei" de "está em falta", e pede desempate quando o texto do
cliente casa com mais de uma coisa.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.resolver import (
    MatchStatus,
    resolve_complement,
    resolve_product,
    split_queries,
)
from app.domain.catalog import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
)


def _complement(group_id, name: str, available: bool = True) -> CatalogComplement:
    return CatalogComplement(
        id=uuid4(),
        group_id=group_id,
        name=name,
        extra_price=Decimal("0"),
        is_available=available,
    )


@pytest.fixture
def catalog() -> CatalogSnapshot:
    pote_id, casquinha_id, milk_id = uuid4(), uuid4(), uuid4()
    sabores_500 = uuid4()

    pote500 = CatalogProduct(
        id=pote_id,
        name="Pote 500ml",
        base_price=Decimal("32.00"),
        groups=[
            CatalogGroup(
                id=sabores_500,
                name="Sabores",
                min_choices=3,
                max_choices=3,
                is_required=True,
                complements=[
                    _complement(sabores_500, "Pistache"),
                    _complement(sabores_500, "Morango"),
                    _complement(sabores_500, "Chocolate Belga"),
                    _complement(sabores_500, "Limão Siciliano"),
                    _complement(sabores_500, "Maracujá", available=False),
                ],
            )
        ],
    )
    pote240 = CatalogProduct(id=uuid4(), name="Pote 240ml", base_price=Decimal("18.00"))
    casquinha = CatalogProduct(id=casquinha_id, name="Casquinha", base_price=Decimal("9.00"))
    milkshake = CatalogProduct(
        id=milk_id, name="Milkshake", base_price=Decimal("22.00"), is_available=False
    )
    return CatalogSnapshot(products=[pote500, pote240, casquinha, milkshake])


# --- produtos ---------------------------------------------------------------

def test_match_exato(catalog: CatalogSnapshot) -> None:
    match = resolve_product("Pote 500ml", catalog)
    assert match.status is MatchStatus.OK
    assert match.product is not None
    assert match.product.name == "Pote 500ml"


def test_ignora_acento_e_maiuscula(catalog: CatalogSnapshot) -> None:
    match = resolve_product("CASQUINHA", catalog)
    assert match.ok
    assert match.product.name == "Casquinha"

    grupo = catalog.products[0].groups[0]
    sabor = resolve_complement("limao siciliano", grupo)
    assert sabor.ok
    assert sabor.complement.name == "Limão Siciliano"


def test_frase_com_ruido_ainda_casa(catalog: CatalogSnapshot) -> None:
    match = resolve_product("quero um pote 500ml por favor", catalog)
    assert match.ok
    assert match.product.name == "Pote 500ml"


def test_ambiguidade_pede_desempate(catalog: CatalogSnapshot) -> None:
    match = resolve_product("quero um pote", catalog)
    assert match.status is MatchStatus.AMBIGUOUS
    assert match.product is None
    assert {p.name for p in match.candidates} == {"Pote 500ml", "Pote 240ml"}


def test_item_inexistente_nao_e_inventado(catalog: CatalogSnapshot) -> None:
    match = resolve_product("pizza de calabresa", catalog)
    assert match.status is MatchStatus.NOT_FOUND
    assert match.product is None
    assert match.candidates == []


def test_produto_indisponivel_tem_status_proprio(catalog: CatalogSnapshot) -> None:
    match = resolve_product("milkshake", catalog)
    assert match.status is MatchStatus.UNAVAILABLE
    assert match.product is None
    assert match.candidates[0].name == "Milkshake"


def test_erro_de_digitacao_cai_na_similaridade(catalog: CatalogSnapshot) -> None:
    match = resolve_product("casquina", catalog)
    assert match.ok
    assert match.product.name == "Casquinha"


# --- complementos -----------------------------------------------------------

def test_complemento_restrito_ao_grupo(catalog: CatalogSnapshot) -> None:
    grupo = catalog.products[0].groups[0]
    match = resolve_complement("pistache", grupo)
    assert match.ok
    assert match.complement.name == "Pistache"


def test_complemento_indisponivel(catalog: CatalogSnapshot) -> None:
    grupo = catalog.products[0].groups[0]
    match = resolve_complement("maracuja", grupo)
    assert match.status is MatchStatus.UNAVAILABLE


def test_complemento_inexistente(catalog: CatalogSnapshot) -> None:
    grupo = catalog.products[0].groups[0]
    match = resolve_complement("bacon", grupo)
    assert match.status is MatchStatus.NOT_FOUND


# --- utilitários ------------------------------------------------------------

def test_split_queries() -> None:
    assert split_queries("pistache, morango e limão") == [
        "pistache",
        "morango",
        "limão",
    ]
