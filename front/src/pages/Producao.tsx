/**
 * Produção — quadro Kanban dos pedidos.
 *
 * Não carrega mais o catálogo: o pedido já vem com nome de produto e de
 * complemento congelados, o que elimina uma requisição e o risco de mostrar o
 * nome atual de um sabor que foi renomeado depois da venda.
 */

import { useState } from 'react';
import { toast } from 'sonner';
import { Header } from '@/components/layout/Header';
import { KanbanColumn } from '@/components/producao/KanbanColumn';
import { QueryError } from '@/components/common/QueryState';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { useOrders } from '@/hooks/use-orders';
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
    <div className="min-h-screen bg-background">
      <Header />
      <main className="container py-6">
        <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Produção</h1>
            <p className="text-muted-foreground">Gerencie o fluxo de pedidos</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => setShowCancelled((v) => !v)}>
            {showCancelled ? 'Ocultar cancelados' : `Mostrar cancelados (${cancelledCount})`}
          </Button>
        </div>

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
      </main>
    </div>
  );
};

export default Producao;
