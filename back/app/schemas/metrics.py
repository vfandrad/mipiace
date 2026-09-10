"""DTOs do dashboard — substituem o `mock-data.ts` do front.

Os nomes dos campos são em português porque é assim que o front já os consome
nos gráficos (dia/pedidos/total, hora/receita...).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.common import Amount, Money


class MetricsRange(StrEnum):
    HOJE = "hoje"
    SEMANA = "semana"
    MES = "mes"


class MetricsSummary(BaseModel):
    total_vendas: Money
    total_pedidos: int
    ticket_medio: Money
    #: Variação % contra o período anterior de mesmo tamanho (pode ser negativa).
    variacao_percentual: Amount
    por_status: dict[str, int] = Field(default_factory=dict)


class DailySales(BaseModel):
    dia: date
    pedidos: int
    total: Money


class ProductSales(BaseModel):
    produto: str
    unidades: int
    receita: Money


class HourlySales(BaseModel):
    hora: int
    pedidos: int
    receita: Money


__all__ = [
    "DailySales",
    "HourlySales",
    "MetricsRange",
    "MetricsSummary",
    "ProductSales",
]
