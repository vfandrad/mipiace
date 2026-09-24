"""CRUD do catálogo (produtos, grupos e complementos).

Toda entrada é validada por schema Pydantic — o painel não consegue mais criar
um grupo "obrigatório com min_choices=0", que era o tipo de dado que travava o
agente na hora de perguntar os sabores.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import SessionDep, bad_request, not_found
from app.schemas.product import (
    ComplementCategoryCreate,
    ComplementCategoryRead,
    ComplementCategoryUpdate,
    ComplementCreate,
    ComplementRead,
    ComplementUpdate,
    GroupCreate,
    GroupRead,
    GroupUpdate,
    ProductCreate,
    ProductGroupCreate,
    ProductGroupRead,
    ProductGroupUpdate,
    ProductList,
    ProductRead,
    ProductUpdate,
    ReorderRequest,
)
from app.services import catalog

router = APIRouter(prefix="/api", tags=["catálogo"])


@router.get("/complement-categories", response_model=list[ComplementCategoryRead])
async def list_complement_categories(session: SessionDep) -> list[ComplementCategoryRead]:
    categories = await catalog.list_complement_categories(session)
    return [ComplementCategoryRead.model_validate(c) for c in categories]


@router.post(
    "/complement-categories",
    response_model=ComplementCategoryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    payload: ComplementCategoryCreate, session: SessionDep
) -> ComplementCategoryRead:
    category = await catalog.create_category(session, payload.model_dump())
    await session.commit()
    return ComplementCategoryRead.model_validate(category)


@router.patch("/complement-categories/{category_id}", response_model=ComplementCategoryRead)
async def update_category(
    category_id: UUID, payload: ComplementCategoryUpdate, session: SessionDep
) -> ComplementCategoryRead:
    category = await catalog.get_category(session, category_id)
    if category is None:
        raise not_found("Categoria não encontrada.")
    await catalog.update_item(session, category, payload.model_dump(exclude_unset=True))
    await session.commit()
    return ComplementCategoryRead.model_validate(category)


@router.delete(
    "/complement-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_category(category_id: UUID, session: SessionDep) -> Response:
    """Apagar a categoria não apaga sabor nenhum.

    O vínculo em `complements.category_id` é ON DELETE SET NULL: os
    sabores continuam no cardápio, só deixam de estar agrupados.
    """
    category = await catalog.get_category(session, category_id)
    if category is None:
        raise not_found("Categoria não encontrada.")
    await catalog.delete_item(session, category)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/catalog/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_catalog(payload: ReorderRequest, session: SessionDep) -> Response:
    """Grava a ordem que o lojista montou arrastando os itens no painel.

    Uma requisição para a lista inteira, e não uma por item: a ordem é uma
    coisa só, e meia ordem gravada sai torta no cardápio do WhatsApp.
    """
    try:
        await catalog.reorder(session, kind=payload.kind, ids=payload.ids)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------


@router.get("/products", response_model=ProductList)
async def list_products(session: SessionDep, only_available: bool = False) -> ProductList:
    products = await catalog.list_products(
        session, only_available=only_available
    )
    return ProductList(products=[ProductRead.model_validate(p) for p in products])


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(payload: ProductCreate, session: SessionDep) -> ProductRead:
    product = await catalog.create_product(session, payload.model_dump())
    await session.commit()
    return ProductRead.model_validate(product)


@router.get("/products/{product_id}", response_model=ProductRead)
async def get_product(product_id: UUID, session: SessionDep) -> ProductRead:
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")
    return ProductRead.model_validate(product)


@router.patch("/products/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: UUID, payload: ProductUpdate, session: SessionDep
) -> ProductRead:
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")
    await catalog.update_item(
        session, product, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return ProductRead.model_validate(product)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: UUID, session: SessionDep) -> Response:
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")
    await catalog.delete_item(session, product)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Grupos de complementos — a biblioteca
# ---------------------------------------------------------------------------
# Um grupo ("Sabores") é uma lista com nome, e vários produtos a usam. Quantas
# escolhas cada produto pede fica no vínculo, logo abaixo.


@router.get("/groups", response_model=list[GroupRead])
async def list_groups(session: SessionDep) -> list[GroupRead]:
    groups = await catalog.list_groups(session)
    return [GroupRead.model_validate(g) for g in groups]


@router.post("/groups", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(payload: GroupCreate, session: SessionDep) -> GroupRead:
    group = await catalog.create_group(session, payload.model_dump())
    await session.commit()
    return GroupRead.model_validate(group)


@router.patch("/groups/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: UUID, payload: GroupUpdate, session: SessionDep
) -> GroupRead:
    group = await catalog.get_group(session, group_id)
    if group is None:
        raise not_found("Grupo não encontrado.")
    await catalog.update_item(session, group, payload.model_dump(exclude_unset=True))
    await session.commit()
    return GroupRead.model_validate(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: UUID, session: SessionDep) -> Response:
    """Apaga a lista inteira — e com ela os itens e todos os vínculos.

    Para tirar o grupo de UM produto sem apagar a lista, use
    `DELETE /api/product-groups/{id}`.
    """
    group = await catalog.get_group(session, group_id)
    if group is None:
        raise not_found("Grupo não encontrado.")
    await catalog.delete_item(session, group)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Vínculo produto <-> grupo (o "importar grupo" do painel)
# ---------------------------------------------------------------------------


@router.post(
    "/products/{product_id}/groups",
    response_model=ProductGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_to_product(
    product_id: UUID, payload: ProductGroupCreate, session: SessionDep
) -> ProductGroupRead:
    """Faz o produto usar um grupo: um que já existe, ou um criado na hora."""
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")

    dados = payload.model_dump()
    group_id = dados.pop("group_id")
    nome = dados.pop("name")

    if group_id is None:
        group = await catalog.create_group(session, {"name": nome, "sort_order": 0})
        group_id = group.id
    elif await catalog.get_group(session, group_id) is None:
        raise not_found("Grupo não encontrado.")

    link = await catalog.link_group(
        session, product_id=product_id, group_id=group_id, data=dados
    )
    await session.commit()
    return ProductGroupRead.model_validate(link)


@router.patch("/product-groups/{link_id}", response_model=ProductGroupRead)
async def update_product_group(
    link_id: UUID, payload: ProductGroupUpdate, session: SessionDep
) -> ProductGroupRead:
    """Muda quantas escolhas ESTE produto pede, e/ou o nome da lista."""
    link = await catalog.get_product_group(session, link_id)
    if link is None:
        raise not_found("Grupo não encontrado neste produto.")

    dados = payload.model_dump(exclude_unset=True)
    nome = dados.pop("name", None)
    if nome is not None:
        # O nome é da lista, não do vínculo — e renomear vale para todo produto
        # que usa a lista, porque é a mesma lista.
        await catalog.update_item(session, link.group, {"name": nome})
    if dados:
        await catalog.update_item(session, link, dados)
    await session.commit()
    return ProductGroupRead.model_validate(link)


@router.delete("/product-groups/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group_from_product(link_id: UUID, session: SessionDep) -> Response:
    """Tira o grupo deste produto. A lista continua existindo para os outros."""
    link = await catalog.get_product_group(session, link_id)
    if link is None:
        raise not_found("Grupo não encontrado neste produto.")
    await catalog.delete_item(session, link)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Complementos
# ---------------------------------------------------------------------------


@router.post(
    "/groups/{group_id}/complements",
    response_model=ComplementRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_complement(
    group_id: UUID, payload: ComplementCreate, session: SessionDep
) -> ComplementRead:
    group = await catalog.get_group(session, group_id)
    if group is None:
        raise not_found("Grupo não encontrado.")
    complement = await catalog.create_complement(
        session, group_id=group_id, data=payload.model_dump()
    )
    await session.commit()
    return ComplementRead.model_validate(complement)


@router.patch("/complements/{complement_id}", response_model=ComplementRead)
async def update_complement(
    complement_id: UUID, payload: ComplementUpdate, session: SessionDep
) -> ComplementRead:
    complement = await catalog.get_complement(session, complement_id)
    if complement is None:
        raise not_found("Complemento não encontrado.")
    await catalog.update_item(
        session, complement, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return ComplementRead.model_validate(complement)


@router.delete("/complements/{complement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_complement(complement_id: UUID, session: SessionDep) -> Response:
    complement = await catalog.get_complement(session, complement_id)
    if complement is None:
        raise not_found("Complemento não encontrado.")
    await catalog.delete_item(session, complement)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
