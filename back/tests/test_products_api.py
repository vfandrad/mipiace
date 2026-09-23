"""API de catálogo: autenticação, validação e formato de resposta.

O banco é substituído pela `FakeSession` do conftest e o repositório é trocado
por funções de mentira — o que está sob teste é o contrato HTTP, que é o que o
front consome.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import catalog as catalog_service

PRODUCT_ID = uuid4()
GROUP_ID = uuid4()


def _complement(name: str = "Pistache", extra: str = "4.00") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        group_id=GROUP_ID,
        name=name,
        extra_price=Decimal(extra),
        is_available=True,
        sort_order=1,
    )


def _group() -> SimpleNamespace:
    return SimpleNamespace(
        id=GROUP_ID,
        product_id=PRODUCT_ID,
        name="Escolha 3 sabores",
        min_choices=3,
        max_choices=3,
        is_required=True,
        sort_order=1,
        complements=[_complement()],
    )


def _product(name: str = "Pote 500ml", price: str = "39.90") -> SimpleNamespace:
    return SimpleNamespace(
        id=PRODUCT_ID,
        name=name,
        description="Pote grande",
        base_price=Decimal(price),
        is_available=True,
        sort_order=1,
        created_at=None,
        updated_at=None,
        groups=[_group()],
    )


@pytest.fixture
def catalogo(monkeypatch):
    async def _list_products(session, *, only_available=False):
        return [_product()]

    monkeypatch.setattr(catalog_service, "list_products", _list_products)


def test_sem_chave_a_api_recusa(client):
    resposta = client.get("/api/products")
    assert resposta.status_code == 401
    assert "detail" in resposta.json()


def test_chave_errada_tambem_recusa(client):
    resposta = client.get("/api/products", headers={"X-API-Key": "chave-errada"})
    assert resposta.status_code == 401


def test_lista_produtos_em_arvore(client, api_key, catalogo):
    resposta = client.get("/api/products", headers={"X-API-Key": api_key})
    assert resposta.status_code == 200

    corpo = resposta.json()
    produto = corpo["products"][0]
    assert produto["name"] == "Pote 500ml"
    assert produto["base_price"] == 39.90          # dinheiro sai como número
    grupo = produto["groups"][0]
    assert grupo["min_choices"] == 3
    assert grupo["complements"][0]["name"] == "Pistache"


def test_cria_produto_com_payload_valido(client, api_key, monkeypatch, fake_session):
    recebido = {}

    async def _create_product(session, data):
        recebido.update(data)
        return _product(name=data["name"], price=str(data["base_price"]))

    monkeypatch.setattr(catalog_service, "create_product", _create_product)

    resposta = client.post(
        "/api/products",
        headers={"X-API-Key": api_key},
        json={"name": "  Pote   500ml ", "base_price": "39.90", "description": "grande"},
    )
    assert resposta.status_code == 201
    assert recebido["name"] == "Pote 500ml"        # normalizado pelo schema
    assert recebido["base_price"] == Decimal("39.90")
    assert fake_session.committed == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"base_price": "10.00"},                      # sem nome
        {"name": "Pote", "base_price": "-1"},         # preço negativo
        {"name": "", "base_price": "10.00"},          # nome vazio
        {"name": "Pote", "base_price": "abc"},        # preço não numérico
    ],
)
def test_payload_invalido_devolve_422(client, api_key, payload):
    resposta = client.post(
        "/api/products", headers={"X-API-Key": api_key}, json=payload
    )
    assert resposta.status_code == 422


def test_produto_inexistente_devolve_404(client, api_key, monkeypatch):
    async def _get_product(session, product_id):
        return None

    monkeypatch.setattr(catalog_service, "get_product", _get_product)

    resposta = client.get(
        f"/api/products/{uuid4()}", headers={"X-API-Key": api_key}
    )
    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "Produto não encontrado."


def test_grupo_obrigatorio_precisa_de_min_choices(client, api_key, monkeypatch):
    """Regra que protege o agente: grupo obrigatório com min=0 é incoerente."""

    async def _get_product(session, product_id):
        return _product()

    monkeypatch.setattr(catalog_service, "get_product", _get_product)

    resposta = client.post(
        f"/api/products/{PRODUCT_ID}/groups",
        headers={"X-API-Key": api_key},
        json={"name": "Sabores", "is_required": True, "min_choices": 0, "max_choices": 3},
    )
    assert resposta.status_code == 422


def test_health_nao_exige_chave(client):
    resposta = client.get("/health")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Categorias de sabor
# ---------------------------------------------------------------------------
# O painel precisa conseguir criar e editar as categorias: elas aparecem no
# cadastro do sabor e agrupam o cardápio que o agente manda, mas até aqui só
# existiam no seed — quem cadastrasse um produto novo não tinha onde criá-las.

def _categoria(name: str = "Sem lactose") -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name=name, sort_order=1)


def test_cria_categoria_de_sabor(client, api_key, monkeypatch, fake_session):
    recebido = {}

    async def _create(session, data):
        recebido.update(data)
        return _categoria(data["name"])

    monkeypatch.setattr(catalog_service, "create_flavor_category", _create)

    resposta = client.post(
        "/api/flavor-categories",
        headers={"X-API-Key": api_key},
        json={"name": "  Frutados  ", "sort_order": 2},
    )
    assert resposta.status_code == 201
    assert recebido["name"] == "Frutados"     # normalizado pelo schema
    assert fake_session.committed == 1


def test_edita_categoria_de_sabor(client, api_key, monkeypatch, fake_session):
    categoria = _categoria()

    async def _get(session, category_id):
        return categoria

    async def _update(session, item, data):
        for campo, valor in data.items():
            setattr(item, campo, valor)
        return item

    monkeypatch.setattr(catalog_service, "get_flavor_category", _get)
    monkeypatch.setattr(catalog_service, "update_item", _update)

    resposta = client.patch(
        f"/api/flavor-categories/{categoria.id}",
        headers={"X-API-Key": api_key},
        json={"name": "Zero lactose"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["name"] == "Zero lactose"


def test_categoria_inexistente_da_404(client, api_key, monkeypatch):
    async def _get(session, category_id):
        return None

    monkeypatch.setattr(catalog_service, "get_flavor_category", _get)

    resposta = client.patch(
        f"/api/flavor-categories/{uuid4()}",
        headers={"X-API-Key": api_key},
        json={"name": "Nada"},
    )
    assert resposta.status_code == 404
