/**
 * Produtos mais vendidos — barras horizontais.
 * Dados de `GET /api/metrics/product-sales`.
 */

import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AXIS_TICK, ChartCard, TOOLTIP_STYLE } from './ChartCard';
import { formatCurrency } from '@/lib/format';
import type { ProductPoint } from '@/types/metrics';

interface ProductsChartProps {
  data: ProductPoint[];
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  onRetry?: () => void;
}

export function ProductsChart({ data, isLoading, isError, error, onRetry }: ProductsChartProps) {
  return (
    <ChartCard
      title="Produtos mais vendidos"
      subtitle="Unidades vendidas"
      isLoading={isLoading}
      isError={isError}
      error={error}
      isEmpty={data.length === 0}
      emptyMessage="Ainda não há vendas no período."
      onRetry={onRetry}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis
            type="category"
            dataKey="name"
            tick={AXIS_TICK}
            axisLine={false}
            tickLine={false}
            width={90}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(value: number, name) =>
              name === 'receita' ? [formatCurrency(value), 'Receita'] : [value, 'Unidades']
            }
          />
          <Bar dataKey="unidades" fill="hsl(var(--chart-2))" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
