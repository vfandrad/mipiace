/**
 * Coluna do quadro Kanban de produção.
 */

import type { Order, OrderStatus } from '@/types/order';
import { OrderCard } from './OrderCard';
import { ORDER_STATUS_INFO } from '@/lib/status';
import { cn } from '@/lib/utils';

interface KanbanColumnProps {
  status: OrderStatus;
  orders: Order[];
  onStatusChange: (orderId: string, newStatus: OrderStatus) => void;
}

export function KanbanColumn({ status, orders, onStatusChange }: KanbanColumnProps) {

  return (
    <div className="kanban-column flex flex-col">
      <div className={cn('pb-3 mb-4 border-b-2', ORDER_STATUS_INFO[status].border)}>
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-foreground">{ORDER_STATUS_INFO[status].plural}</h3>
          <span className="flex items-center justify-center h-6 w-6 rounded-full bg-card text-sm font-medium shadow-sm">
            {orders.length}
          </span>
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto scrollbar-thin pr-1">
        {orders.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
            Nenhum pedido
          </div>
        ) : (
          orders.map((order) => (
            <OrderCard key={order.id} order={order} onStatusChange={onStatusChange} />
          ))
        )}
      </div>
    </div>
  );
}
