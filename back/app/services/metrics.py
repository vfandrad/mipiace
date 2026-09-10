"""Métricas do dashboard.

Só faz a costura entre o SQL (repositories/metrics.py) e os DTOs: a definição
de "venda" mora nas views do banco.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import metrics as metrics_repo
from app.schemas.metrics import (
    DailySales,
    HourlySales,
    MetricsRange,
    MetricsSummary,
    ProductSales,
)
from app.services.pricing import money

ZERO = Decimal("0.00")


def _variation(current: Decimal, previous: Decimal) -> Decimal:
    """Variação % contra o período anterior.

    Sem base de comparação (período anterior zerado) devolvemos 0 em vez de
    "+100%": o dashboard não deve inventar crescimento no primeiro dia de uso.
    """
    if previous <= ZERO:
        return ZERO
    return ((current - previous) / previous * 100).quantize(Decimal("0.1"))


async def get_summary(
    session: AsyncSession, *, range_: MetricsRange = MetricsRange.HOJE
) -> MetricsSummary:
    days = metrics_repo.RANGE_DAYS[range_.value]
    totals = await metrics_repo.summary_totals(session, days=days)
    by_status = await metrics_repo.summary_by_status(session, days=days)

    total_vendas = money(metrics_repo.as_decimal(totals["total_vendas"]))
    total_pedidos = int(totals["total_pedidos"])
    anterior = metrics_repo.as_decimal(totals["total_anterior"])
    ticket = money(total_vendas / total_pedidos) if total_pedidos else ZERO

    return MetricsSummary(
        total_vendas=total_vendas,
        total_pedidos=total_pedidos,
        ticket_medio=ticket,
        variacao_percentual=_variation(total_vendas, anterior),
        por_status=by_status,
    )


async def get_daily_sales(session: AsyncSession, *, days: int = 7) -> list[DailySales]:
    rows = await metrics_repo.daily_sales(session, days=days)
    return [
        DailySales(
            dia=row["dia"],
            pedidos=int(row["pedidos"]),
            total=money(metrics_repo.as_decimal(row["total"])),
        )
        for row in rows
    ]


async def get_product_sales(
    session: AsyncSession,
    *,
    limit: int = 10,
    range_: MetricsRange = MetricsRange.SEMANA,
) -> list[ProductSales]:
    days = metrics_repo.RANGE_DAYS[range_.value]
    rows = await metrics_repo.product_sales(session, limit=limit, days=days)
    return [
        ProductSales(
            produto=row["produto"],
            unidades=int(row["unidades"]),
            receita=money(metrics_repo.as_decimal(row["receita"])),
        )
        for row in rows
    ]


async def get_hourly_sales(
    session: AsyncSession, *, range_: MetricsRange = MetricsRange.SEMANA
) -> list[HourlySales]:
    days = metrics_repo.RANGE_DAYS[range_.value]
    rows = await metrics_repo.hourly_sales(session, days=days)
    return [
        HourlySales(
            hora=int(row["hora"]),
            pedidos=int(row["pedidos"]),
            receita=money(metrics_repo.as_decimal(row["receita"])),
        )
        for row in rows
    ]


__all__ = [
    "get_daily_sales",
    "get_hourly_sales",
    "get_product_sales",
    "get_summary",
]
