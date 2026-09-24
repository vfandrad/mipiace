/**
 * Tabela de pedidos recentes do dashboard.
 */

import type { Order } from '@/types/order';
import { PaymentBadge, StatusBadge } from '@/components/ui/status-badge';
import { EmptyState } from '@/components/common/QueryState';
import { formatCurrency, formatTime, toMillis } from '@/lib/format';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

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
