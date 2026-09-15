/**
 * Rótulos e cores dos status — a única tabela de status do painel.
 *
 * Antes cada tela mantinha a sua (Kanban, Dashboard, StatusBadge e a lista de
 * pedidos recentes), e elas divergiam. Aqui ficam o texto e o *tom* de cor;
 * cada tela monta a classe do jeito que precisa, porque os usos são diferentes:
 * a coluna do Kanban pinta uma borda, o Dashboard pinta um bloco inteiro e o
 * badge pinta uma pílula.
 */

import type { OrderStatus, PaymentStatus } from '@/types/order';

/** Tom de cor de cada status; vira classe Tailwind nas funções abaixo. */
type Tone = 'new' | 'production' | 'ready' | 'delivered' | 'danger';

interface StatusInfo {
  /** Texto no singular: "Novo" (badge de um pedido). */
  label: string;
  /** Texto no plural: "Novos" (cabeçalho de coluna/bloco contador). */
  plural: string;
  tone: Tone;
}

export const ORDER_STATUS_INFO: Record<OrderStatus, StatusInfo> = {
  novo: { label: 'Novo', plural: 'Novos', tone: 'new' },
  preparando: { label: 'Preparando', plural: 'Preparando', tone: 'production' },
  entrega: { label: 'Saiu p/ entrega', plural: 'Em entrega', tone: 'ready' },
  finalizado: { label: 'Finalizado', plural: 'Finalizados', tone: 'delivered' },
  cancelado: { label: 'Cancelado', plural: 'Cancelados', tone: 'danger' },
};

/** Pílula do badge de status. */
export function statusPillClass(status: OrderStatus): string {
  const tone = ORDER_STATUS_INFO[status].tone;
  return tone === 'danger'
    ? 'bg-destructive/10 text-destructive font-medium'
    : `status-${tone}`;
}

/** Borda inferior do cabeçalho da coluna do Kanban. */
export function statusBorderClass(status: OrderStatus): string {
  const tone = ORDER_STATUS_INFO[status].tone;
  return tone === 'danger' ? 'border-b-destructive' : `border-b-status-${tone}`;
}

/** Fundo e texto do bloco contador do Dashboard. */
export function statusTileClass(status: OrderStatus): { bg: string; text: string } {
  const tone = ORDER_STATUS_INFO[status].tone;
  if (tone === 'danger') return { bg: 'bg-destructive/10', text: 'text-destructive' };
  return { bg: `bg-status-${tone}-bg`, text: `text-status-${tone}` };
}

const PAYMENT_INFO: Record<PaymentStatus, { label: string; className: string }> = {
  pago: { label: 'Pago', className: 'bg-status-ready-bg text-status-ready' },
  pendente: { label: 'Pix pendente', className: 'bg-status-production-bg text-status-production' },
  expirado: { label: 'Pix expirado', className: 'bg-destructive/10 text-destructive' },
  cancelado: { label: 'Pgto. cancelado', className: 'bg-destructive/10 text-destructive' },
  reembolsado: { label: 'Reembolsado', className: 'bg-status-delivered-bg text-status-delivered' },
};

export function paymentInfo(status: PaymentStatus): { label: string; className: string } {
  return (
    PAYMENT_INFO[status] ?? {
      label: status,
      className: 'bg-secondary text-secondary-foreground',
    }
  );
}

/**
 * Próximo status no fluxo do balcão — espelha as transições que o backend
 * aceita em `services/orders.py::ORDER_TRANSITIONS`. `cancelado` não entra no
 * avanço: sai por botão próprio.
 */
const NEXT_STATUS: Record<OrderStatus, OrderStatus | null> = {
  novo: 'preparando',
  preparando: 'entrega',
  entrega: 'finalizado',
  finalizado: null,
  cancelado: null,
};

export function nextOrderStatus(status: OrderStatus): OrderStatus | null {
  return NEXT_STATUS[status];
}
