/**
 * A tela de Producao: o Kanban dos pedidos.
 *
 * So le e muda o status do pedido; nao edita nada do cardapio.
 */

import type { Order, OrderStatus } from '@/tipos';
import { ORDER_STATUS_INFO, nextOrderStatus } from '@/formato';
import { cn } from '@/formato';
import { useState } from 'react';
import { Check, ChefHat, Clock, Copy, MapPin, Store, Truck, XCircle, Eye, EyeOff } from 'lucide-react';
import { Button } from '@/ui';
import { PaymentBadge } from '@/ui';
import { formatCurrency, formatPhone, formatTime, minutesSince } from '@/formato';
import { formatAddress } from '@/formato';
import { toast } from 'sonner';
import { Page, PageTitle } from '@/comuns';
import { QueryError } from '@/comuns';
import { Skeleton } from '@/ui';
import { useOrders } from '@/dados';
import { RefreshButton } from '@/comuns';

// ---------------------------------------------------------------
// KanbanColumn
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// OrderCard
// ---------------------------------------------------------------

interface OrderCardProps {
  order: Order;
  onStatusChange: (orderId: string, newStatus: OrderStatus) => void;
}

const ACTION_CONFIG: Partial<
  Record<OrderStatus, { label: string; icon: React.ReactNode; className: string }>
> = {
  preparando: {
    label: 'Iniciar preparo',
    icon: <ChefHat className="h-4 w-4" />,
    className: 'action-btn-warning',
  },
  entrega: {
    label: 'Saiu p/ entrega',
    icon: <Truck className="h-4 w-4" />,
    className: 'action-btn-success',
  },
  finalizado: {
    label: 'Finalizar',
    icon: <Check className="h-4 w-4" />,
    className: 'action-btn-secondary',
  },
};

export function OrderCard({ order, onStatusChange }: OrderCardProps) {
  const [copied, setCopied] = useState(false);
  const minutesAgo = minutesSince(order.created_at);
  const isOpen = order.status !== 'finalizado' && order.status !== 'cancelado';
  const isUrgent = minutesAgo > 15 && isOpen;
  const nextStatus = nextOrderStatus(order.status);
  const action = nextStatus ? ACTION_CONFIG[nextStatus] : null;
  const address = formatAddress(order);
  const pixCode = order.payment_status === 'pendente' ? order.payment?.qr_code : null;

  const copyPix = async () => {
    if (!pixCode) return;
    try {
      await navigator.clipboard.writeText(pixCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Sem clipboard (http, permissão negada): o código segue visível na tela.
      setCopied(false);
    }
  };

  return (
    <div
      className={cn(
        'order-card',
        order.status === 'novo' && 'animate-pulse-subtle border-status-new/30',
        isUrgent && 'border-destructive/50',
        order.status === 'cancelado' && 'opacity-70',
      )}
    >
      {/* Código do pedido + horário */}
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-xs font-semibold text-muted-foreground">
          {order.code || '—'}
        </span>
        <div className="flex items-center gap-1 text-sm text-muted-foreground shrink-0">
          <Clock className="h-3.5 w-3.5" />
          <span>{formatTime(order.created_at)}</span>
          <span className={cn('text-xs', isUrgent && 'text-destructive font-medium')}>
            ({minutesAgo}min)
          </span>
        </div>
      </div>

      {/* Cliente */}
      <div className="mb-2">
        <p className="font-semibold text-foreground truncate">
          {order.customer_name || 'Cliente sem nome'}
        </p>
        {order.customer_phone && (
          <p className="text-xs text-muted-foreground">{formatPhone(order.customer_phone)}</p>
        )}
      </div>

      {/* Pagamento */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <PaymentBadge status={order.payment_status} />
      </div>

      {/* Endereço de entrega */}
      {/* Retirada precisa estar visível no card: é a diferença entre despachar
          o pedido e deixá-lo no balcão esperando o cliente. Sem isso, o Kanban
          mostrava só a ausência de endereço, que é fácil confundir com dado
          faltando. */}
      {order.fulfillment_type === 'retirada' && (
        <div className="flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--status-production))]">
          <Store className="h-3.5 w-3.5 shrink-0" />
          <span>Retirada na loja</span>
        </div>
      )}

      {address && (
        <div className="flex items-start gap-1.5 text-sm text-muted-foreground mb-3">
          <MapPin className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>{address}</span>
        </div>
      )}

      {/* Itens */}
      <div className="space-y-2 mb-3">
        {order.items.length === 0 ? (
          <p className="text-sm text-muted-foreground italic">Pedido sem itens.</p>
        ) : (
          order.items.map((item) => (
            <div key={item.id} className="text-sm">
              <div className="flex justify-between gap-2">
                <span className="font-medium">
                  {item.quantity}x {item.product_name_snapshot}
                </span>
                <span className="text-muted-foreground shrink-0">
                  {formatCurrency(item.line_total)}
                </span>
              </div>
              {item.details && (
                <p className="text-muted-foreground text-xs italic mt-0.5">{item.details}</p>
              )}
              {item.complements.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {item.complements.map((complement, index) => (
                    <span
                      key={complement.id ?? `${item.id}-${index}`}
                      className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-secondary text-secondary-foreground"
                    >
                      {complement.complement_name_snapshot}
                      {complement.extra_price_snapshot > 0 &&
                        ` +${formatCurrency(complement.extra_price_snapshot)}`}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {order.notes && (
        <p className="text-xs bg-secondary/60 rounded p-2 mb-3">
          <span className="font-medium">Obs.: </span>
          {order.notes}
        </p>
      )}

      {/* Totais */}
      <div className="border-t border-border pt-3 space-y-1">
        {order.delivery_fee > 0 && (
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Subtotal / entrega</span>
            <span>
              {formatCurrency(order.subtotal)} + {formatCurrency(order.delivery_fee)}
            </span>
          </div>
        )}
        <div className="flex items-center justify-between">
          <span className="font-medium">Total</span>
          <span className="text-lg font-semibold">{formatCurrency(order.total)}</span>
        </div>
      </div>

      {/* Pix pendente: o balcão consegue reenviar o copia-e-cola ao cliente */}
      {pixCode && (
        <div className="mt-3 rounded-lg border border-status-production/40 bg-status-production-bg p-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-status-production">Pix aguardando</span>
            <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs" onClick={copyPix}>
              <Copy className="h-3 w-3" />
              {copied ? 'Copiado!' : 'Copiar código'}
            </Button>
          </div>
          <p className="mt-1 font-mono text-[10px] leading-tight text-muted-foreground break-all line-clamp-2">
            {pixCode}
          </p>
        </div>
      )}

      {/* Ações */}
      {isOpen && (
        <div className="mt-3 flex gap-2">
          {nextStatus && action && (
            <Button
              onClick={() => onStatusChange(order.id, nextStatus)}
              className={cn('flex-1 gap-2', action.className)}
              size="sm"
            >
              {action.icon}
              {action.label}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive"
            onClick={() => onStatusChange(order.id, 'cancelado')}
            title="Cancelar pedido"
            aria-label="Cancelar pedido"
          >
            <XCircle className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Producao
// ---------------------------------------------------------------

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
