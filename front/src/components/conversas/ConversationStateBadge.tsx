/**
 * Estado da máquina de conversa em forma de badge.
 * Cobre os 10 estados de `ConversationState`; estado desconhecido cai num
 * visual neutro em vez de sumir da tela.
 */

import { cn } from '@/lib/utils';

const STATE_LABELS: Record<string, { label: string; className: string }> = {
  saudacao: { label: 'Saudação', className: 'bg-status-new-bg text-status-new' },
  escolhendo_produto: {
    label: 'Escolhendo produto',
    className: 'bg-status-new-bg text-status-new',
  },
  personalizando_item: {
    label: 'Personalizando item',
    className: 'bg-status-production-bg text-status-production',
  },
  revisando_carrinho: {
    label: 'Revisando carrinho',
    className: 'bg-status-production-bg text-status-production',
  },
  coletando_endereco: {
    label: 'Coletando endereço',
    className: 'bg-status-production-bg text-status-production',
  },
  confirmando_pedido: {
    label: 'Confirmando pedido',
    className: 'bg-status-production-bg text-status-production',
  },
  aguardando_pagamento: {
    label: 'Aguardando pagamento',
    className: 'bg-status-production-bg text-status-production',
  },
  concluido: { label: 'Concluído', className: 'bg-status-ready-bg text-status-ready' },
  atendimento_humano: {
    label: 'Atendimento humano',
    className: 'bg-destructive/10 text-destructive',
  },
  cancelado: { label: 'Cancelado', className: 'bg-destructive/10 text-destructive' },
};

interface Props {
  state: string;
  className?: string;
}

export function ConversationStateBadge({ state, className }: Props) {
  const config = STATE_LABELS[state] ?? {
    label: state?.replace(/_/g, ' ') || 'desconhecido',
    className: 'bg-secondary text-secondary-foreground',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap',
        config.className,
        className,
      )}
    >
      {config.label}
    </span>
  );
}
