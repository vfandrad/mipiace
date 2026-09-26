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
GROUP_ID = uuid4()       # a lista compartilhada ("Sabores")
LINK_ID = uuid4()        # o vínculo deste produto com ela


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
    """O grupo como o produto o usa: o vínculo achatado com a lista.

    `id` é do vínculo (é o que se edita para mudar quantos sabores ESTE produto
    pede) e `group_id` é da lista, que outros produtos também usam.
    """
    return SimpleNamespace(
        id=LINK_ID,
        group_id=GROUP_ID,
        name="Sabores",
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


def test_apagar_produto_ja_usado_em_pedido_devolve_409(client, api_key, monkeypatch):
    """`ON DELETE RESTRICT` (order_items.product_id) não pode virar um 500 cru.

    Achado em auditoria: apagar um produto ou sabor que já foi vendido faz o
    Postgres recusar a exclusão (pra não perder o histórico do pedido) — sem
    um handler pra isso, o painel travava com um erro de banco em vez de uma
    mensagem que o lojista entende.
    """
    from sqlalchemy.exc import IntegrityError

    async def _get_product(session, product_id):
        return _product()

    async def _delete_item(session, item):
        raise IntegrityError("DELETE FROM products", {}, Exception("restrict"))

    monkeypatch.setattr(catalog_service, "get_product", _get_product)
    monkeypatch.setattr(catalog_service, "delete_item", _delete_item)

    resposta = client.delete(
        f"/api/products/{PRODUCT_ID}", headers={"X-API-Key": api_key}
    )
    assert resposta.status_code == 409
    assert "pedido" in resposta.json()["detail"].lower()


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

    monkeypatch.setattr(catalog_service, "create_category", _create)

    resposta = client.post(
        "/api/complement-categories",
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

    monkeypatch.setattr(catalog_service, "get_category", _get)
    monkeypatch.setattr(catalog_service, "update_item", _update)

    resposta = client.patch(
        f"/api/complement-categories/{categoria.id}",
        headers={"X-API-Key": api_key},
        json={"name": "Zero lactose"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["name"] == "Zero lactose"


def test_categoria_inexistente_da_404(client, api_key, monkeypatch):
    async def _get(session, category_id):
        return None

    monkeypatch.setattr(catalog_service, "get_category", _get)

    resposta = client.patch(
        f"/api/complement-categories/{uuid4()}",
        headers={"X-API-Key": api_key},
        json={"name": "Nada"},
    )
    assert resposta.status_code == 404


# ---------------------------------------------------------------------------
# Ordem (arrastar e soltar)
# ---------------------------------------------------------------------------

def test_reordenar_grava_a_posicao_de_cada_item(client, api_key, monkeypatch, fake_session):
    recebido = {}

    async def _reorder(session, *, kind, ids):
        recebido["kind"] = kind
        recebido["ids"] = ids
        return len(ids)

    monkeypatch.setattr(catalog_service, "reorder", _reorder)

    a, b = uuid4(), uuid4()
    resposta = client.post(
        "/api/catalog/reorder",
        headers={"X-API-Key": api_key},
        json={"kind": "product", "ids": [str(b), str(a)]},
    )
    assert resposta.status_code == 204
    assert recebido["kind"] == "product"
    assert recebido["ids"] == [b, a]      # a ordem enviada é a ordem gravada
    assert fake_session.committed == 1


def test_reordenar_tipo_desconhecido_e_recusado(client, api_key):
    resposta = client.post(
        "/api/catalog/reorder",
        headers={"X-API-Key": api_key},
        json={"kind": "pedido", "ids": [str(uuid4())]},
    )
    assert resposta.status_code == 422


def test_reordenar_lista_vazia_e_recusado(client, api_key):
    resposta = client.post(
        "/api/catalog/reorder",
        headers={"X-API-Key": api_key},
        json={"kind": "product", "ids": []},
    )
    assert resposta.status_code == 422


# ---------------------------------------------------------------------------
# Grupo compartilhado entre produtos
# ---------------------------------------------------------------------------
# A lista de opções ("Sabores") é uma só e vários produtos a usam; o que muda
# por produto é quantas escolhas ele pede. Estes testes guardam os dois lados
# desse contrato.


@pytest.fixture
def vinculo(monkeypatch):
    """Captura o que a rota mandou para o serviço, sem banco nenhum."""
    registro: dict = {}

    async def _get_product(session, product_id):
        return _product()

    async def _get_group(session, group_id):
        return SimpleNamespace(id=group_id, name="Sabores", sort_order=0, complements=[])

    async def _create_group(session, data):
        registro["grupo_criado"] = data
        return SimpleNamespace(id=GROUP_ID, name=data["name"], sort_order=0, complements=[])

    async def _link_group(session, *, product_id, group_id, data):
        registro["vinculo"] = {"product_id": product_id, "group_id": group_id, **data}
        return _group()

    monkeypatch.setattr(catalog_service, "get_product", _get_product)
    monkeypatch.setattr(catalog_service, "get_group", _get_group)
    monkeypatch.setattr(catalog_service, "create_group", _create_group)
    monkeypatch.setattr(catalog_service, "link_group", _link_group)
    return registro


def test_usar_grupo_existente_nao_cria_outra_lista(client, api_key, vinculo):
    """O "importar grupo": aponta a lista que já existe, com a regra deste produto."""
    resposta = client.post(
        f"/api/products/{PRODUCT_ID}/groups",
        headers={"X-API-Key": api_key},
        json={"group_id": str(GROUP_ID), "min_choices": 2, "max_choices": 2, "is_required": True},
    )
    assert resposta.status_code == 201
    assert "grupo_criado" not in vinculo          # nenhuma lista nova nasceu
    assert vinculo["vinculo"]["group_id"] == GROUP_ID
    assert vinculo["vinculo"]["min_choices"] == 2


def test_criar_grupo_pelo_nome_cria_a_lista_e_vincula(client, api_key, vinculo):
    resposta = client.post(
        f"/api/products/{PRODUCT_ID}/groups",
        headers={"X-API-Key": api_key},
        json={"name": "  Coberturas ", "min_choices": 0, "max_choices": 1},
    )
    assert resposta.status_code == 201
    assert vinculo["grupo_criado"]["name"] == "Coberturas"   # normalizado
    assert vinculo["vinculo"]["product_id"] == PRODUCT_ID


@pytest.mark.parametrize(
    "payload",
    [
        # Nem os dois...
        {"group_id": str(GROUP_ID), "name": "Sabores"},
        # ...nem nenhum.
        {"min_choices": 1, "max_choices": 2},
        # Obrigatório com min=0 travaria o agente na hora de perguntar.
        {"name": "Sabores", "min_choices": 0, "max_choices": 2, "is_required": True},
        # max menor que min não descreve escolha nenhuma.
        {"name": "Sabores", "min_choices": 3, "max_choices": 1},
    ],
)
def test_vinculo_invalido_devolve_422(client, api_key, vinculo, payload):
    resposta = client.post(
        f"/api/products/{PRODUCT_ID}/groups", headers={"X-API-Key": api_key}, json=payload
    )
    assert resposta.status_code == 422


def test_editar_o_vinculo_muda_a_regra_e_o_nome_da_lista(client, api_key, monkeypatch):
    """Renomear vale para a lista inteira; a regra de escolha, só para este produto."""
    grupo = SimpleNamespace(id=GROUP_ID, name="Sabores", sort_order=0, complements=[])
    link = _group()
    link.group = grupo
    escritas: list[tuple[str, dict]] = []

    async def _get_product_group(session, link_id):
        return link

    async def _update_item(session, item, data):
        escritas.append(("grupo" if item is grupo else "vinculo", data))
        return item

    monkeypatch.setattr(catalog_service, "get_product_group", _get_product_group)
    monkeypatch.setattr(catalog_service, "update_item", _update_item)

    resposta = client.patch(
        f"/api/product-groups/{LINK_ID}",
        headers={"X-API-Key": api_key},
        json={"name": "Sabores do dia", "min_choices": 4, "max_choices": 4},
    )
    assert resposta.status_code == 200
    assert ("grupo", {"name": "Sabores do dia"}) in escritas
    assert ("vinculo", {"min_choices": 4, "max_choices": 4}) in escritas


def test_remover_o_grupo_do_produto_nao_apaga_a_lista(client, api_key, monkeypatch):
    apagados: list = []
    link = _group()

    async def _get_product_group(session, link_id):
        return link

    async def _delete_item(session, item):
        apagados.append(item)

    monkeypatch.setattr(catalog_service, "get_product_group", _get_product_group)
    monkeypatch.setattr(catalog_service, "delete_item", _delete_item)

    resposta = client.delete(
        f"/api/product-groups/{LINK_ID}", headers={"X-API-Key": api_key}
    )
    assert resposta.status_code == 204
    # O que sai é o VÍNCULO, nunca a lista: os outros produtos continuam com ela.
    assert apagados == [link]
