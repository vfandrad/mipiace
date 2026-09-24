"""DTOs do catálogo (produtos, grupos de escolha e complementos).

Validação de verdade em vez de `data: dict`: o painel só consegue criar um
grupo coerente (max >= min, min <= nº de complementos) porque o contrato está
aqui, não espalhado nas rotas.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import Money, ORMModel

# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


class ComplementRead(ORMModel):
    id: UUID
    group_id: UUID
    name: str
    extra_price: Money
    is_available: bool
    sort_order: int
    category_id: UUID | None = None


class GroupRead(ORMModel):
    """Um grupo da biblioteca: a lista com nome, sem regra de escolha.

    A regra ("escolhe 2 a 3") não está aqui porque ela é de cada produto que usa
    o grupo — mora em `ProductGroupRead`.
    """

    id: UUID
    name: str
    sort_order: int
    complements: list[ComplementRead] = Field(default_factory=list)


class ProductGroupRead(ORMModel):
    """Um grupo COMO ESTE PRODUTO O USA — é o que o painel e o agente leem.

    Achata o vínculo e o grupo numa coisa só: `id` é o do vínculo (é o que se
    edita para mudar quantos sabores este produto pede, ou se desvincula),
    `group_id` é o da lista compartilhada.
    """

    id: UUID
    group_id: UUID
    name: str
    min_choices: int
    max_choices: int
    is_required: bool
    sort_order: int
    complements: list[ComplementRead] = Field(default_factory=list)


class ProductRead(ORMModel):
    id: UUID
    name: str
    description: str | None = None
    base_price: Money
    is_available: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    groups: list[ProductGroupRead] = Field(default_factory=list)


class ProductList(BaseModel):
    """Envelope de `GET /api/products` (contrato do SPEC)."""

    products: list[ProductRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("nome não pode ser vazio")
    return cleaned


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    base_price: Money
    is_available: bool = True
    sort_order: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return _clean_name(value)


class ProductUpdate(BaseModel):
    """PATCH: só os campos enviados são alterados."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    base_price: Money | None = None
    is_available: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None


class GroupCreate(BaseModel):
    """Cria a lista na biblioteca. Vincular a um produto é outra operação."""

    name: str = Field(min_length=1, max_length=120)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return _clean_name(value)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None


def _validar_escolhas(min_choices: int, max_choices: int, is_required: bool) -> None:
    if max_choices < min_choices:
        raise ValueError("max_choices não pode ser menor que min_choices")
    if is_required and min_choices < 1:
        # Grupo obrigatório com min=0 é contraditório e travaria o agente, que
        # decide "falta escolher?" olhando min_choices.
        raise ValueError("grupo obrigatório precisa de min_choices >= 1")


class ProductGroupCreate(BaseModel):
    """Faz um produto usar um grupo — o "importar grupo" do painel.

    Ou aponta um grupo que já existe (`group_id`), ou cria um novo pelo nome
    (`name`). Os dois caminhos numa requisição só porque, na tela, "usar o grupo
    Sabores" e "criar o grupo Coberturas" são o mesmo gesto.
    """

    group_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    min_choices: int = Field(default=0, ge=0)
    max_choices: int = Field(default=1, ge=1)
    is_required: bool = False
    sort_order: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None

    @model_validator(mode="after")
    def _check(self) -> ProductGroupCreate:
        if (self.group_id is None) == (self.name is None):
            raise ValueError("informe group_id (usar um grupo) ou name (criar um)")
        _validar_escolhas(self.min_choices, self.max_choices, self.is_required)
        return self


class ProductGroupUpdate(BaseModel):
    """Edita o grupo como este produto o usa.

    A regra de escolha é deste produto. O `name` é da lista compartilhada, então
    renomear aqui renomeia para todos os produtos que a usam — que é o
    esperado, é a mesma lista. Os dois vêm juntos porque, na tela, "editar o
    grupo Sabores deste produto" é um gesto só.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    min_choices: int | None = Field(default=None, ge=0)
    max_choices: int | None = Field(default=None, ge=1)
    is_required: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None

    @model_validator(mode="after")
    def _check_range(self) -> ProductGroupUpdate:
        if (
            self.min_choices is not None
            and self.max_choices is not None
            and self.max_choices < self.min_choices
        ):
            raise ValueError("max_choices não pode ser menor que min_choices")
        return self


class ComplementCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    extra_price: Money = Decimal("0")
    is_available: bool = True
    sort_order: int = Field(default=0, ge=0)
    category_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return _clean_name(value)


class ComplementUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    extra_price: Money | None = None
    is_available: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    category_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None


class ComplementCategoryRead(ORMModel):
    id: UUID
    name: str
    sort_order: int


class ComplementCategoryCreate(BaseModel):
    """Categoria de sabor ("Sem lactose", "Clássicos", "Frutados"...).

    É o lojista que decide quais existem: numa sorveteria são restrições, numa
    hamburgueria seriam outras coisas. Por isso a lista é dado, não constante
    de código.
    """

    name: str = Field(min_length=1, max_length=120)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return _clean_name(value)


class ComplementCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None


class ReorderRequest(BaseModel):
    """A nova ordem de uma lista, como ela ficou na tela depois do arrasto."""

    kind: Literal["product", "group", "product_group", "complement", "category"]
    ids: list[UUID] = Field(min_length=1, max_length=500)


__all__ = [
    "ComplementCreate",
    "ComplementRead",
    "ComplementUpdate",
    "ComplementCategoryCreate",
    "ComplementCategoryRead",
    "ComplementCategoryUpdate",
    "GroupCreate",
    "GroupRead",
    "GroupUpdate",
    "ProductGroupCreate",
    "ProductGroupRead",
    "ProductGroupUpdate",
    "ProductCreate",
    "ProductList",
    "ProductRead",
    "ProductUpdate",
    "ReorderRequest",
]
