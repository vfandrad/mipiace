/**
 * Métricas do dashboard.
 *
 * Substitui o antigo `mock-data.ts`: cada gráfico tem sua própria query, com
 * loading/erro/vazio próprios, para que uma métrica quebrada não apague a tela
 * inteira. O período do filtro entra na queryKey, então trocar de período
 * realmente refaz a busca.
 */

import { useQuery } from '@tanstack/react-query';
import {
  fetchDailySales,
  fetchHourlySales,
  fetchMetricsSummary,
  fetchProductSales,
} from '@/lib/api';
import { RANGE_TO_DAYS, toHourlyPoints, toProductPoints, toSalesPoints } from '@/lib/transforms';
import type { MetricsRange } from '@/types/metrics';

const STALE_TIME = 30_000;

export function useMetricsSummary(range: MetricsRange) {
  return useQuery({
    queryKey: ['metrics', 'summary', range],
    queryFn: () => fetchMetricsSummary(range),
    staleTime: STALE_TIME,
  });
}

export function useDailySales(range: MetricsRange) {
  return useQuery({
    queryKey: ['metrics', 'daily-sales', range],
    queryFn: () => fetchDailySales(RANGE_TO_DAYS[range], range),
    select: toSalesPoints,
    staleTime: STALE_TIME,
  });
}

export function useProductSales(range: MetricsRange) {
  return useQuery({
    queryKey: ['metrics', 'product-sales', range],
    queryFn: () => fetchProductSales(range),
    select: (rows) => toProductPoints(rows),
    staleTime: STALE_TIME,
  });
}

export function useHourlySales(range: MetricsRange) {
  return useQuery({
    queryKey: ['metrics', 'hourly-sales', range],
    queryFn: () => fetchHourlySales(range),
    select: toHourlyPoints,
    staleTime: STALE_TIME,
  });
}

/** Agrupa as quatro queries — o Admin só precisa de um objeto. */
export function useMetrics(range: MetricsRange) {
  const summary = useMetricsSummary(range);
  const daily = useDailySales(range);
  const products = useProductSales(range);
  const hourly = useHourlySales(range);

  return {
    summary,
    daily,
    products,
    hourly,
    /** Refaz tudo — usado pelo botão "tentar de novo". */
    refetchAll: () => {
      summary.refetch();
      daily.refetch();
      products.refetch();
      hourly.refetch();
    },
  };
}
