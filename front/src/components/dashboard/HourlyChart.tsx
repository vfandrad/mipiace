/**
 * Distribuição de pedidos por hora do dia — área.
 * Dados de `GET /api/metrics/hourly-sales`.
 */

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AXIS_TICK, ChartCard, TOOLTIP_STYLE } from './ChartCard';
import { formatCurrency } from '@/lib/format';
import type { HourlyPoint } from '@/types/metrics';

interface HourlyChartProps {
  data: HourlyPoint[];
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  onRetry?: () => void;
}

export function HourlyChart({ data, isLoading, isError, error, onRetry }: HourlyChartProps) {
  return (
    <ChartCard
      title="Pedidos por horário"
      subtitle="Onde está o pico de movimento"
      isLoading={isLoading}
      isError={isError}
      error={error}
      isEmpty={data.length === 0}
      emptyMessage="Ainda não há vendas no período."
      onRetry={onRetry}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
          <defs>
            <linearGradient id="colorOrders" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="hsl(var(--chart-3))" stopOpacity={0.3} />
              <stop offset="95%" stopColor="hsl(var(--chart-3))" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={34} allowDecimals={false} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(value: number, name) =>
              name === 'receita' ? [formatCurrency(value), 'Receita'] : [value, 'Pedidos']
            }
          />
          <Area
            type="monotone"
            dataKey="pedidos"
            stroke="hsl(var(--chart-3))"
            strokeWidth={2}
            fillOpacity={1}
            fill="url(#colorOrders)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
