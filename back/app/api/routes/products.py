"""CRUD do catálogo (produtos, grupos e complementos).

Toda entrada é validada por schema Pydantic — o painel não consegue mais criar
um grupo "obrigatório com min_choices=0", que era o tipo de dado que travava o
agente na hora de perguntar os sabores.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import SessionDep, not_found
from app.services import catalog
from app.schemas.product import (
    ComplementCreate,
    ComplementRead,
    ComplementUpdate,
    FlavorCategoryCreate,
    FlavorCategoryRead,
    FlavorCategoryUpdate,
    GroupCreate,
    GroupRead,
    GroupUpdate,
    ProductCreate,
    ProductList,
    ProductRead,
    ProductUpdate,
)

router = APIRouter(prefix="/api", tags=["catálogo"])


@router.get("/flavor-categories", response_model=list[FlavorCategoryRead])
async def list_flavor_categories(session: SessionDep) -> list[FlavorCategoryRead]:
    categories = await catalog.list_flavor_categories(session)
    return [FlavorCategoryRead.model_validate(c) for c in categories]


@router.post(
    "/flavor-categories",
    response_model=FlavorCategoryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_flavor_category(
    payload: FlavorCategoryCreate, session: SessionDep
) -> FlavorCategoryRead:
    category = await catalog.create_flavor_category(session, payload.model_dump())
    await session.commit()
    return FlavorCategoryRead.model_validate(category)


@router.patch("/flavor-categories/{category_id}", response_model=FlavorCategoryRead)
async def update_flavor_category(
    category_id: UUID, payload: FlavorCategoryUpdate, session: SessionDep
) -> FlavorCategoryRead:
    category = await catalog.get_flavor_category(session, category_id)
    if category is None:
        raise not_found("Categoria não encontrada.")
    await catalog.update_item(session, category, payload.model_dump(exclude_unset=True))
    await session.commit()
    return FlavorCategoryRead.model_validate(category)


@router.delete(
    "/flavor-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_flavor_category(category_id: UUID, session: SessionDep) -> Response:
    """Apagar a categoria não apaga sabor nenhum.

    O vínculo em `complements.flavor_category_id` é ON DELETE SET NULL: os
    sabores continuam no cardápio, só deixam de estar agrupados.
    """
    category = await catalog.get_flavor_category(session, category_id)
    if category is None:
        raise not_found("Categoria não encontrada.")
    await catalog.delete_item(session, category)
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
# Grupos de complementos
# ---------------------------------------------------------------------------


@router.post(
    "/products/{product_id}/groups",
    response_model=GroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    product_id: UUID, payload: GroupCreate, session: SessionDep
) -> GroupRead:
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")
    group = await catalog.create_group(
        session, product_id=product_id, data=payload.model_dump()
    )
    await session.commit()
    return GroupRead.model_validate(group)


@router.patch("/groups/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: UUID, payload: GroupUpdate, session: SessionDep
) -> GroupRead:
    group = await catalog.get_group(session, group_id)
    if group is None:
        raise not_found("Grupo não encontrado.")
    await catalog.update_item(
        session, group, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return GroupRead.model_validate(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: UUID, session: SessionDep) -> Response:
    group = await catalog.get_group(session, group_id)
    if group is None:
        raise not_found("Grupo não encontrado.")
    await catalog.delete_item(session, group)
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
