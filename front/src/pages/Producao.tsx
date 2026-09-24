/**
 * Produção — quadro Kanban dos pedidos.
 *
 * Não carrega mais o catálogo: o pedido já vem com nome de produto e de
 * complemento congelados, o que elimina uma requisição e o risco de mostrar o
 * nome atual de um sabor que foi renomeado depois da venda.
 */

import { useState } from 'react';
import { toast } from 'sonner';
import { Page, PageTitle } from '@/components/layout/Page';
import { KanbanColumn } from '@/components/producao/KanbanColumn';
import { QueryError } from '@/components/common/QueryState';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { useOrders } from '@/hooks/use-orders';
import { RefreshButton } from '@/components/common/RefreshButton';
import { Eye, EyeOff } from 'lucide-react';
import { ORDER_STATUS_INFO } from '@/lib/status';
import type { OrderStatus } from '@/types/order';
import { cn } from '@/lib/utils';

// "novo" (pix pendente) fica de fora: o pedido só entra no quadro quando o
// Pix é confirmado — é o próprio backend que move o pedido para "preparando"
// no momento em que o pagamento cai (ver services/orders.py::apply_payment_result).
const KANBAN_STATUSES: OrderStatus[] = ['preparando', 'entrega', 'finalizado'];

const Producao = () => {
  const { orders, isLoading, isError, error, refetch, changeStatus } = useOrders();
  const [showCancelled, setShowCancelled] = useState(false);

  const handleStatusChange = (orderId: string, newStatus: OrderStatus) => {
    changeStatus(orderId, newStatus);
    toast.success('Status atualizado', {
      description: `Pedido movido para ${ORDER_STATUS_INFO[newStatus].label}`,
    });
  };

  const columns = showCancelled ? [...KANBAN_STATUSES, 'cancelado' as OrderStatus] : KANBAN_STATUSES;
  const cancelledCount = orders.filter((order) => order.status === 'cancelado').length;

  return (
    <Page className="space-y-6">
      <PageTitle
        title="Produção"
        subtitle="Gerencie o fluxo de pedidos"
        actions={
          <>
            {/* Olho no lugar do texto: "Mostrar cancelados (0)" ocupava metade
                da faixa no celular para uma ação secundária. O contador vira um
                selo ao lado quando existe algo escondido. O `title` faz as
                vezes de dica — o projeto não usa componente de tooltip. */}
            <Button
              variant="outline"
              size="icon"
              className="relative h-11 w-11 sm:h-9 sm:w-9"
              aria-pressed={showCancelled}
              title={showCancelled ? 'Ocultar cancelados' : 'Mostrar cancelados'}
              aria-label={
                showCancelled
                  ? 'Ocultar pedidos cancelados'
                  : `Mostrar pedidos cancelados (${cancelledCount})`
              }
              onClick={() => setShowCancelled((v) => !v)}
            >
              {showCancelled ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
              {!showCancelled && cancelledCount > 0 && (
                <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-[11px] font-medium text-destructive-foreground">
                  {cancelledCount}
                </span>
              )}
            </Button>
            <RefreshButton onRefresh={() => refetch()} />
          </>
        }
      />

      {isError ? (
        <QueryError
          error={error}
          onRetry={() => refetch()}
          title="Não foi possível carregar os pedidos"
        />
      ) : isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {KANBAN_STATUSES.map((status) => (
            <Skeleton key={status} className="h-64 rounded-lg" />
          ))}
        </div>
      ) : (
        <div
          className={cn(
            'grid grid-cols-1 md:grid-cols-2 gap-4',
            showCancelled ? 'xl:grid-cols-4' : 'xl:grid-cols-3',
          )}
        >
          {columns.map((status) => (
            <KanbanColumn
              key={status}
              status={status}
              orders={orders.filter((order) => order.status === status)}
              onStatusChange={handleStatusChange}
            />
          ))}
        </div>
      )}
    </Page>
  );
};

export default Producao;
