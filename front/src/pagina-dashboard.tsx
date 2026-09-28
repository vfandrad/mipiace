/**
 * A tela de Dashboard: numeros do banco, sem logica propria.
 *
 * Tudo aqui e leitura — os cartoes e graficos primeiro, a tela no fim.
 */

import { QueryState, EmptyState, QueryError } from '@/comuns';
import { TrendingDown, TrendingUp, DollarSign, Package, ShoppingCart } from 'lucide-react';
import { cn } from '@/formato';
import { formatPercent, formatCurrency, formatTime, toMillis, formatInteger, toNumber } from '@/formato';
import { Button } from '@/ui';
import type { MetricsRange, SalesPoint, HourlyPoint, ProductPoint } from '@/tipos';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Area, AreaChart, Bar, BarChart } from 'recharts';
import type { Order, OrderStatus } from '@/tipos';
import { PaymentBadge, StatusBadge } from '@/ui';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/ui';
import { useState } from 'react';
import { Page, PageTitle } from '@/comuns';
import { RefreshButton } from '@/comuns';
import { Skeleton } from '@/ui';
import { useMetrics } from '@/dados';
import { useOrders } from '@/dados';
import { STORE_NAME } from '@/api';
import { ORDER_STATUS_INFO } from '@/formato';
import { RANGE_LABELS } from '@/formato';

// ---------------------------------------------------------------
// ChartCard
// ---------------------------------------------------------------

interface ChartCardProps {
  title: string;
  subtitle?: string;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  isEmpty: boolean;
  emptyMessage: string;
  onRetry?: () => void;
  children: React.ReactNode;
}

export function ChartCard({
  title,
  subtitle,
  isLoading,
  isError,
  error,
  isEmpty,
  emptyMessage,
  onRetry,
  children,
}: ChartCardProps) {
  return (
    <div className="kpi-card">
      <div className="mb-4">
        <h3 className="font-semibold text-sm sm:text-base">{title}</h3>
        {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
      </div>
      <div className="h-[200px] sm:h-[280px]">
        <QueryState
          isLoading={isLoading}
          isError={isError}
          error={error}
          isEmpty={isEmpty}
          emptyMessage={emptyMessage}
          onRetry={onRetry}
        >
          {children}
        </QueryState>
      </div>
    </div>
  );
}

/** Estilo compartilhado das tooltips do Recharts (segue os tokens do tema). */
export const TOOLTIP_STYLE = {
  backgroundColor: 'hsl(var(--card))',
  border: '1px solid hsl(var(--border))',
  borderRadius: '8px',
  fontSize: '12px',
} as const;

export const AXIS_TICK = { fill: 'hsl(var(--muted-foreground))', fontSize: 11 } as const;

// ---------------------------------------------------------------
// KPICard
// ---------------------------------------------------------------

interface KPICardProps {
  title: string;
  /** Já formatado por quem chama (moeda, inteiro, ...). */
  value: string | number;
  /** Variação percentual; omitir esconde o rodapé. */
  change?: number;
  changeLabel?: string;
  icon?: React.ReactNode;
  className?: string;
}

export function KPICard({ title, value, change, changeLabel, icon, className }: KPICardProps) {
  const isPositive = typeof change === 'number' && change > 0;
  const isNegative = typeof change === 'number' && change < 0;

  return (
    <div className={cn('kpi-card animate-fade-in', className)}>
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <p className="text-3xl font-semibold tracking-tight">
            {typeof value === 'number' ? value.toLocaleString('pt-BR') : value}
          </p>
        </div>
        {icon && <div className="p-2 rounded-lg bg-secondary">{icon}</div>}
      </div>

      {change !== undefined && (
        <div className="mt-4 flex items-center gap-2">
          <div
            className={cn(
              'flex items-center gap-1 text-sm font-medium',
              isPositive && 'text-status-ready',
              isNegative && 'text-destructive',
              !isPositive && !isNegative && 'text-muted-foreground',
            )}
          >
            {isPositive && <TrendingUp className="h-4 w-4" />}
            {isNegative && <TrendingDown className="h-4 w-4" />}
            <span>{formatPercent(change)}</span>
          </div>
          {changeLabel && <span className="text-sm text-muted-foreground">{changeLabel}</span>}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// DateFilter
// ---------------------------------------------------------------

const PERIODS: { value: MetricsRange; label: string }[] = [
  { value: 'hoje', label: 'Hoje' },
  { value: 'semana', label: 'Semana' },
  { value: 'mes', label: 'Mês' },
];

interface DateFilterProps {
  value: MetricsRange;
  onChange: (range: MetricsRange) => void;
}

export function DateFilter({ value, onChange }: DateFilterProps) {
  return (
    <div className="flex items-center bg-secondary rounded-lg p-1" role="group" aria-label="Período">
      {PERIODS.map((option) => (
        <Button
          key={option.value}
          variant="ghost"
          size="sm"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            value === option.value
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------
// SalesChart
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// HourlyChart
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// ProductsChart
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// RecentOrders
// ---------------------------------------------------------------

interface RecentOrdersProps {
  orders: Order[];
  limit?: number;
}

export function RecentOrders({ orders, limit = 10 }: RecentOrdersProps) {
  const rows = [...orders]
    .sort((a, b) => toMillis(b.created_at) - toMillis(a.created_at))
    .slice(0, limit);

  return (
    <div className="kpi-card">
      <h3 className="font-semibold mb-4">Pedidos recentes</h3>
      {rows.length === 0 ? (
        <EmptyState message="Nenhum pedido registrado ainda." />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Código</TableHead>
                <TableHead>Cliente</TableHead>
                <TableHead>Itens</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Pagamento</TableHead>
                <TableHead>Hora</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((order) => (
                <TableRow key={order.id} className="animate-fade-in">
                  <TableCell className="font-mono text-xs">{order.code || '-'}</TableCell>
                  <TableCell className="font-medium">{order.customer_name || '-'}</TableCell>
                  <TableCell className="max-w-[220px] truncate">
                    {order.items
                      .map((item) => `${item.quantity}x ${item.product_name_snapshot}`)
                      .join(', ') || '-'}
                  </TableCell>
                  <TableCell className="text-right font-medium">
                    {formatCurrency(order.total)}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={order.status} />
                  </TableCell>
                  <TableCell>
                    <PaymentBadge status={order.payment_status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatTime(order.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------

// Os 4 status que o lojista acompanha no bloco "Status de produção".
const PRODUCTION_STATUSES: OrderStatus[] = ['novo', 'preparando', 'entrega', 'finalizado'];

const Dashboard = () => {
  const [range, setRange] = useState<MetricsRange>('semana');
  const { summary, daily, products, hourly, refetchAll } = useMetrics(range);
  const orders = useOrders();

  const periodLabel = RANGE_LABELS[range];
  const data = summary.data;

  /**
   * `por_status` vem das métricas; se o backend não mandar, contamos a partir
   * dos pedidos carregados para o Kanban em vez de mostrar zero.
   */
  const statusCount = (status: OrderStatus): number => {
    const fromMetrics = data?.por_status?.[status];
    if (typeof fromMetrics === 'number') return fromMetrics;
    return orders.orders.filter((order) => order.status === status).length;
  };

  return (
    <Page className="space-y-6">
      <PageTitle
        title="Dashboard"
        subtitle={`Acompanhe o desempenho de ${STORE_NAME}`}
        actions={
          <>
            <DateFilter value={range} onChange={setRange} />
            <RefreshButton onRefresh={() => refetchAll()} />
          </>
        }
      />

      {/* KPIs */}
      {summary.isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-32 rounded-lg" />
          ))}
        </div>
      ) : summary.isError ? (
        <QueryError
          error={summary.error}
          onRetry={() => summary.refetch()}
          title="Não foi possível carregar os indicadores"
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <KPICard
            title={`Vendas (${range})`}
            value={formatCurrency(data?.total_vendas)}
            change={toNumber(data?.variacao_percentual)}
            changeLabel="vs período anterior"
            icon={<DollarSign className="h-5 w-5 text-muted-foreground" />}
          />
          <KPICard
            title="Pedidos"
            value={formatInteger(data?.total_pedidos)}
            icon={<ShoppingCart className="h-5 w-5 text-muted-foreground" />}
          />
          <KPICard
            title="Ticket médio"
            value={formatCurrency(data?.ticket_medio)}
            icon={<TrendingUp className="h-5 w-5 text-muted-foreground" />}
          />
          <KPICard
            title="Em produção agora"
            value={formatInteger(statusCount('novo') + statusCount('preparando'))}
            icon={<Package className="h-5 w-5 text-muted-foreground" />}
          />
        </div>
      )}

      {/* Gráficos */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SalesChart
          data={daily.data ?? []}
          isLoading={daily.isLoading}
          isError={daily.isError}
          error={daily.error}
          onRetry={() => daily.refetch()}
          periodLabel={periodLabel}
        />
        <ProductsChart
          data={products.data ?? []}
          isLoading={products.isLoading}
          isError={products.isError}
          error={products.error}
          onRetry={() => products.refetch()}
        />
        <HourlyChart
          data={hourly.data ?? []}
          isLoading={hourly.isLoading}
          isError={hourly.isError}
          error={hourly.error}
          onRetry={() => hourly.refetch()}
        />

        <div className="kpi-card">
          <h3 className="font-semibold mb-4 text-sm sm:text-base">Status de produção</h3>
          {orders.isLoading && summary.isLoading ? (
            <div className="grid grid-cols-2 gap-3">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {PRODUCTION_STATUSES.map((status) => (
                // `tile` traz fundo e texto juntos; a legenda usa opacity-80
                // em vez de `text-...(/80)` porque cor montada com barra é
                // outra classe que o Tailwind não enxergaria (ver lib/status).
                <div
                  key={status}
                  className={cn('p-3 sm:p-4 rounded-lg', ORDER_STATUS_INFO[status].tile)}
                >
                  <p className="text-2xl sm:text-3xl font-bold">{statusCount(status)}</p>
                  <p className="text-xs sm:text-sm opacity-80 mt-1">
                    {ORDER_STATUS_INFO[status].plural}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Pedidos recentes */}
      {orders.isError ? (
        <QueryError
          error={orders.error}
          onRetry={() => orders.refetch()}
          title="Não foi possível carregar os pedidos recentes"
        />
      ) : orders.isLoading ? (
        <Skeleton className="h-48 rounded-lg" />
      ) : (
        <RecentOrders orders={orders.orders} />
      )}
    </Page>
  );
};

export default Dashboard;
