"""DTOs do catálogo (produtos, grupos de escolha e complementos).

Validação de verdade em vez de `data: dict`: o painel só consegue criar um
grupo coerente (max >= min, min <= nº de complementos) porque o contrato está
aqui, não espalhado nas rotas.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
    flavor_category_id: UUID | None = None


class GroupRead(ORMModel):
    id: UUID
    product_id: UUID
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
    groups: list[GroupRead] = Field(default_factory=list)


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
    name: str = Field(min_length=1, max_length=120)
    min_choices: int = Field(default=0, ge=0)
    max_choices: int = Field(default=1, ge=1)
    is_required: bool = False
    sort_order: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return _clean_name(value)

    @model_validator(mode="after")
    def _check_range(self) -> GroupCreate:
        if self.max_choices < self.min_choices:
            raise ValueError("max_choices não pode ser menor que min_choices")
        if self.is_required and self.min_choices < 1:
            # Grupo obrigatório com min=0 é contraditório e travaria o agente,
            # que decide "falta escolher?" olhando min_choices.
            raise ValueError("grupo obrigatório precisa de min_choices >= 1")
        return self


class GroupUpdate(BaseModel):
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
    def _check_range(self) -> GroupUpdate:
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
    flavor_category_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return _clean_name(value)


class ComplementUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    extra_price: Money | None = None
    is_available: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    flavor_category_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None


class FlavorCategoryRead(ORMModel):
    id: UUID
    name: str
    sort_order: int


__all__ = [
    "ComplementCreate",
    "ComplementRead",
    "ComplementUpdate",
    "FlavorCategoryRead",
    "GroupCreate",
    "GroupRead",
    "GroupUpdate",
    "ProductCreate",
    "ProductList",
    "ProductRead",
    "ProductUpdate",
]
