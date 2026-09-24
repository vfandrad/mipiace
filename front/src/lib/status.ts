/**
 * Rótulos e cores dos status — a única tabela de status do painel.
 *
 * Antes cada tela mantinha a sua (Kanban, Dashboard, StatusBadge e a lista de
 * pedidos recentes), e elas divergiam. Aqui ficam o texto e as classes.
 *
 * **As classes são literais, e isso não é verbosidade — é o que faz o estilo
 * existir.** Antes este arquivo guardava um *tom* (`'new'`, `'ready'`) e três
 * funções montavam a classe por interpolação: `` `status-${tone}` ``,
 * `` `border-b-status-${tone}` ``, `` `bg-status-${tone}-bg` ``. O Tailwind
 * descobre quais classes gerar varrendo o texto do código-fonte; string montada
 * em tempo de execução ele não enxerga, então essas classes simplesmente não
 * iam para o CSS final. No build, `border-b-status-*` e `.status-new` tinham
 * zero ocorrências: a barra colorida do cabeçalho das colunas do Kanban e todas
 * as pílulas de status saíam sem cor nenhuma em produção.
 *
 * Por isso cada classe aqui aparece inteira, escrita à mão. É a regra da casa:
 * nenhuma classe do Tailwind pode ser montada por concatenação.
 */

import type { OrderStatus, PaymentStatus } from '@/types/order';

interface StatusInfo {
  /** Texto no singular: "Novo" (badge de um pedido). */
  label: string;
  /** Texto no plural: "Novos" (cabeçalho de coluna/bloco contador). */
  plural: string;
  /** Pílula do badge. */
  pill: string;
  /** Borda inferior do cabeçalho da coluna do Kanban. */
  border: string;
  /** Bloco contador do Dashboard. */
  tile: string;
}

export const ORDER_STATUS_INFO: Record<OrderStatus, StatusInfo> = {
  novo: {
    label: 'Novo',
    plural: 'Novos',
    pill: 'bg-status-new-bg text-status-new font-medium',
    border: 'border-b-status-new',
    tile: 'bg-status-new-bg text-status-new',
  },
  preparando: {
    label: 'Preparando',
    plural: 'Preparando',
    pill: 'bg-status-production-bg text-status-production font-medium',
    border: 'border-b-status-production',
    tile: 'bg-status-production-bg text-status-production',
  },
  entrega: {
    label: 'Saiu p/ entrega',
    plural: 'Em entrega',
    pill: 'bg-status-ready-bg text-status-ready font-medium',
    border: 'border-b-status-ready',
    tile: 'bg-status-ready-bg text-status-ready',
  },
  finalizado: {
    label: 'Finalizado',
    plural: 'Finalizados',
    pill: 'bg-status-delivered-bg text-status-delivered font-medium',
    border: 'border-b-status-delivered',
    tile: 'bg-status-delivered-bg text-status-delivered',
  },
  cancelado: {
    label: 'Cancelado',
    plural: 'Cancelados',
    pill: 'bg-destructive/10 text-destructive font-medium',
    border: 'border-b-destructive',
    tile: 'bg-destructive/10 text-destructive',
  },
};

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
