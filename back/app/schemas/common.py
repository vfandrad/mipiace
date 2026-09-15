"""Tipos compartilhados pelos DTOs da API."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

#: Dinheiro trafega como número JSON (12.5), não string.
#: Internamente continua sendo `Decimal` — a conversão só acontece na borda,
#: na serialização, para o front não precisar de `Number(...)` em todo lugar.
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=10, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]

#: Igual a `Money`, mas sem o piso de zero (variações percentuais, deltas).
Amount = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
]


class ORMModel(BaseModel):
    """DTO lido diretamente de um objeto SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)


__all__ = ["Amount", "Money", "ORMModel"]
