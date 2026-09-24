/**
 * Card de pedido no Kanban.
 *
 * Os complementos já chegam com nome do backend (snapshot congelado na venda),
 * então este componente não depende mais do catálogo para renderizar.
 */

import { useState } from 'react';
import { Check, ChefHat, Clock, Copy, MapPin, Store, Truck, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PaymentBadge } from '@/components/ui/status-badge';
import { cn } from '@/lib/utils';
import { formatCurrency, formatPhone, formatTime, minutesSince } from '@/lib/format';
import { formatAddress } from '@/lib/transforms';
import { nextOrderStatus } from '@/lib/status';
import type { Order, OrderStatus } from '@/types/order';

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
