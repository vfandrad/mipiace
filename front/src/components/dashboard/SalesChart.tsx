/**
 * Vendas por dia — linha. Dados de `GET /api/metrics/daily-sales`.
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { AXIS_TICK, ChartCard, TOOLTIP_STYLE } from './ChartCard';
import { formatCurrency } from '@/lib/format';
import type { SalesPoint } from '@/types/metrics';

interface SalesChartProps {
  data: SalesPoint[];
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  onRetry?: () => void;
  periodLabel: string;
}

export function SalesChart({
  data,
  isLoading,
  isError,
  error,
  onRetry,
  periodLabel,
}: SalesChartProps) {
  return (
    <ChartCard
      title="Vendas por dia"
      subtitle={`Pedidos pagos ${periodLabel}`}
      isLoading={isLoading}
      isError={isError}
      error={error}
      isEmpty={data.length === 0}
      emptyMessage="Ainda não há vendas no período."
      onRetry={onRetry}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis
            tick={AXIS_TICK}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value: number) => `R$${value}`}
            width={54}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(value: number, name) =>
              name === 'total' ? [formatCurrency(value), 'Total'] : [value, 'Pedidos']
            }
          />
          <Line
            type="monotone"
            dataKey="total"
            stroke="hsl(var(--chart-1))"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5, fill: 'hsl(var(--chart-1))' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
