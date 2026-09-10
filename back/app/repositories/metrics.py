"""SQL do dashboard.

Usa as views criadas em `schema.sql` (vw_daily_sales, vw_product_sales,
vw_hourly_sales) — assim a definição de "venda válida" (pago e não cancelado)
mora num lugar só, o banco, e não é reescrita em cada endpoint.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Quantos dias cada faixa do dashboard cobre (inclusive o dia de hoje).
RANGE_DAYS: dict[str, int] = {"hoje": 1, "semana": 7, "mes": 30}

#: O que conta como venda. As views do schema já embutem esta regra, mas elas
#: agregam sobre todo o histórico e por isso não servem para as consultas que
#: precisam respeitar o filtro de período do dashboard. Para não escrever a
#: regra em dois lugares, os SQLs por período reaproveitam este fragmento.
_VALID_SALE = "o.payment_status = 'pago' AND o.status <> 'cancelado'"

#: Início da janela: hoje = só hoje; semana = últimos 7 dias, contando hoje.
_WINDOW_START = "date_trunc('day', now()) - make_interval(days => :days - 1)"

_PERIOD_CTE = """
WITH bounds AS (
    SELECT date_trunc('day', now()) - make_interval(days => :days - 1) AS inicio,
           date_trunc('day', now()) - make_interval(days => 2 * :days - 1) AS inicio_anterior
)
"""

_SUMMARY_SQL = text(
    _PERIOD_CTE
    + """
SELECT
    (SELECT coalesce(sum(o.total), 0) FROM orders o, bounds b
      WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
        AND o.created_at >= b.inicio)                                AS total_vendas,
    (SELECT count(*) FROM orders o, bounds b
      WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
        AND o.created_at >= b.inicio)                                AS total_pedidos,
    (SELECT coalesce(sum(o.total), 0) FROM orders o, bounds b
      WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
        AND o.created_at >= b.inicio_anterior AND o.created_at < b.inicio)
                                                                     AS total_anterior
"""
)

_STATUS_SQL = text(
    _PERIOD_CTE
    + """
SELECT o.status::text AS status, count(*) AS quantidade
FROM orders o, bounds b
WHERE o.created_at >= b.inicio
GROUP BY 1
"""
)

# generate_series garante dia sem venda no gráfico (senão a linha "pula" datas).
_DAILY_SQL = text(
    """
SELECT d.dia::date            AS dia,
       coalesce(v.pedidos, 0) AS pedidos,
       coalesce(v.total, 0)   AS total
FROM generate_series(
        date_trunc('day', now()) - make_interval(days => :days - 1),
        date_trunc('day', now()),
        interval '1 day'
     ) AS d(dia)
LEFT JOIN vw_daily_sales v ON v.dia = d.dia::date
ORDER BY d.dia
"""
)

_PRODUCT_SQL = text(
    f"""
SELECT oi.product_name_snapshot AS produto,
       sum(oi.quantity)         AS unidades,
       sum(oi.line_total)       AS receita
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE {_VALID_SALE}
  AND o.created_at >= {_WINDOW_START}
GROUP BY 1
ORDER BY receita DESC, unidades DESC
LIMIT :limit
"""
)

# generate_series mantém as 24 faixas no gráfico mesmo sem venda na hora.
_HOURLY_SQL = text(
    f"""
SELECT h.hora                 AS hora,
       coalesce(v.pedidos, 0) AS pedidos,
       coalesce(v.receita, 0) AS receita
FROM generate_series(0, 23) AS h(hora)
LEFT JOIN (
    SELECT extract(hour FROM o.created_at)::int AS hora,
           count(*)                             AS pedidos,
           coalesce(sum(o.total), 0)            AS receita
    FROM orders o
    WHERE {_VALID_SALE}
      AND o.created_at >= {_WINDOW_START}
    GROUP BY 1
) v ON v.hora = h.hora
ORDER BY h.hora
"""
)


async def summary_totals(session: AsyncSession, *, days: int) -> dict[str, Any]:
    row = (await session.execute(_SUMMARY_SQL, {"days": days})).mappings().one()
    return dict(row)


async def summary_by_status(session: AsyncSession, *, days: int) -> dict[str, int]:
    rows = (await session.execute(_STATUS_SQL, {"days": days})).mappings().all()
    return {row["status"]: int(row["quantidade"]) for row in rows}


async def daily_sales(session: AsyncSession, *, days: int) -> list[dict[str, Any]]:
    rows = (await session.execute(_DAILY_SQL, {"days": days})).mappings().all()
    return [dict(row) for row in rows]


async def product_sales(
    session: AsyncSession, *, limit: int = 10, days: int = 7
) -> list[dict[str, Any]]:
    rows = (
        (await session.execute(_PRODUCT_SQL, {"limit": limit, "days": days}))
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def hourly_sales(session: AsyncSession, *, days: int = 7) -> list[dict[str, Any]]:
    rows = (await session.execute(_HOURLY_SQL, {"days": days})).mappings().all()
    return [dict(row) for row in rows]


def as_decimal(value: Any) -> Decimal:
    """`sum()` do Postgres volta como Decimal, mas 0 pode vir como int."""
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


__all__ = [
    "RANGE_DAYS",
    "as_decimal",
    "daily_sales",
    "hourly_sales",
    "product_sales",
    "summary_by_status",
    "summary_totals",
]
