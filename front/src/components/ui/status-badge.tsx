/**
 * Badges de status de pedido e de pagamento.
 * Os rótulos e cores vêm de `lib/status.ts`, que é a tabela única do painel.
 */

import type { OrderStatus, PaymentStatus } from '@/types/order';
import { ORDER_STATUS_INFO, paymentInfo } from '@/lib/status';
import { cn } from '@/lib/utils';

interface StatusBadgeProps {
  status: OrderStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium',
        ORDER_STATUS_INFO[status].pill,
        className,
      )}
    >
      {ORDER_STATUS_INFO[status].label}
    </span>
  );
}

interface PaymentBadgeProps {
  status: PaymentStatus;
  className?: string;
}

export function PaymentBadge({ status, className }: PaymentBadgeProps) {
  const info = paymentInfo(status);
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium',
        info.className,
        className,
      )}
    >
      {info.label}
    </span>
  );
}
