/**
 * Badges de status de pedido e de pagamento.
 * Os rótulos cobrem todos os valores dos enums do backend, inclusive os que a
 * UI antiga ignorava (`cancelado`, `expirado`, `reembolsado`).
 */

import type { OrderStatus, PaymentStatus } from '@/types/order';
import { cn } from '@/lib/utils';

const STATUS_CONFIG: Record<OrderStatus, { label: string; className: string }> = {
  novo: { label: 'Novo', className: 'status-new' },
  preparando: { label: 'Preparando', className: 'status-production' },
  entrega: { label: 'Saiu p/ entrega', className: 'status-ready' },
  finalizado: { label: 'Finalizado', className: 'status-delivered' },
  cancelado: { label: 'Cancelado', className: 'bg-destructive/10 text-destructive font-medium' },
};

interface StatusBadgeProps {
  status: OrderStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? { label: status, className: 'bg-secondary' };
  return (
    <span
      className={cn(
        'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium',
        config.className,
        className,
      )}
    >
      {config.label}
    </span>
  );
}

const PAYMENT_CONFIG: Record<PaymentStatus, { label: string; className: string }> = {
  pago: { label: 'Pago', className: 'bg-status-ready-bg text-status-ready' },
  pendente: { label: 'Pix pendente', className: 'bg-status-production-bg text-status-production' },
  expirado: { label: 'Pix expirado', className: 'bg-destructive/10 text-destructive' },
  cancelado: { label: 'Pgto. cancelado', className: 'bg-destructive/10 text-destructive' },
  reembolsado: { label: 'Reembolsado', className: 'bg-status-delivered-bg text-status-delivered' },
};

interface PaymentBadgeProps {
  status: PaymentStatus;
  className?: string;
}

export function PaymentBadge({ status, className }: PaymentBadgeProps) {
  const config = PAYMENT_CONFIG[status] ?? {
    label: status,
    className: 'bg-secondary text-secondary-foreground',
  };
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium',
        config.className,
        className,
      )}
    >
      {config.label}
    </span>
  );
}
