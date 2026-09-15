/**
 * Dashboard — KPIs, gráficos e pedidos recentes.
 *
 * Tudo aqui vem de `/api/metrics/*`; não há mais nenhum dado inventado no
 * front. O filtro de período entra na queryKey e refaz as buscas de verdade.
 */

import { useState } from 'react';
import { DollarSign, Package, ShoppingCart, TrendingUp } from 'lucide-react';
import { Header } from '@/components/layout/Header';
import { KPICard } from '@/components/dashboard/KPICard';
import { SalesChart } from '@/components/dashboard/SalesChart';
import { ProductsChart } from '@/components/dashboard/ProductsChart';
import { HourlyChart } from '@/components/dashboard/HourlyChart';
import { DateFilter } from '@/components/dashboard/DateFilter';
import { RecentOrders } from '@/components/dashboard/RecentOrders';
import { QueryError } from '@/components/common/QueryState';
import { Skeleton } from '@/components/ui/skeleton';
import { useMetrics } from '@/hooks/use-metrics';
import { useOrders } from '@/hooks/use-orders';
import { formatCurrency, formatInteger, toNumber } from '@/lib/format';
import { ORDER_STATUS_INFO, statusTileClass } from '@/lib/status';
import { RANGE_LABELS } from '@/lib/transforms';
import type { MetricsRange } from '@/types/metrics';
import type { OrderStatus } from '@/types/order';

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
    <div className="min-h-screen bg-background">
      <Header />
      <main className="container py-6 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
            <p className="text-muted-foreground">Acompanhe o desempenho da sua gelateria</p>
          </div>
          <DateFilter value={range} onChange={setRange} />
        </div>

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
                {PRODUCTION_STATUSES.map((status) => {
                  const tile = statusTileClass(status);
                  return (
                    <div key={status} className={`p-3 sm:p-4 rounded-lg ${tile.bg}`}>
                      <p className={`text-2xl sm:text-3xl font-bold ${tile.text}`}>
                        {statusCount(status)}
                      </p>
                      <p className={`text-xs sm:text-sm ${tile.text}/80 mt-1`}>
                        {ORDER_STATUS_INFO[status].plural}
                      </p>
                    </div>
                  );
                })}
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

        <div className="flex justify-end">
          <button
            type="button"
            onClick={refetchAll}
            className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-4"
          >
            Atualizar métricas
          </button>
        </div>
      </main>
    </div>
  );
};

export default Dashboard;
