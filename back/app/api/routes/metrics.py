"""Métricas do dashboard — substituem o `mock-data.ts` do front."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.schemas.metrics import (
    DailySales,
    HourlySales,
    MetricsRange,
    MetricsSummary,
    ProductSales,
)
from app.services import metrics as metrics_service

router = APIRouter(prefix="/api/metrics", tags=["métricas"])


@router.get("/summary", response_model=MetricsSummary)
async def summary(
    session: SessionDep, range: MetricsRange = MetricsRange.HOJE
) -> MetricsSummary:
    """Cartões do topo do dashboard, comparados com o período anterior."""
    return await metrics_service.get_summary(session, range_=range)


@router.get("/daily-sales", response_model=list[DailySales])
async def daily_sales(
    session: SessionDep, days: int = Query(default=7, ge=1, le=90)
) -> list[DailySales]:
    return await metrics_service.get_daily_sales(session, days=days)


@router.get("/product-sales", response_model=list[ProductSales])
async def product_sales(
    session: SessionDep,
    limit: int = Query(default=10, ge=1, le=50),
    range: MetricsRange = MetricsRange.SEMANA,
) -> list[ProductSales]:
    """Respeita o mesmo filtro de período do resto do dashboard."""
    return await metrics_service.get_product_sales(session, limit=limit, range_=range)


@router.get("/hourly-sales", response_model=list[HourlySales])
async def hourly_sales(
    session: SessionDep, range: MetricsRange = MetricsRange.SEMANA
) -> list[HourlySales]:
    return await metrics_service.get_hourly_sales(session, range_=range)
