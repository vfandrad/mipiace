/**
 * Estado da máquina de conversa em forma de badge.
 *
 * São seis estados desde a redução do agente: a etapa do diálogo (escolhendo
 * produto, personalizando item, revisando carrinho…) virou dado do pedido, e
 * o estado guarda só o que muda o que o sistema pode fazer. Os nomes antigos
 * continuam no mapa porque há conversas gravadas com eles.
 */

import { cn } from '@/lib/utils';

const STATE_LABELS: Record<string, { label: string; className: string }> = {
  conversando: {
    label: 'Montando pedido',
    className: 'bg-status-new-bg text-status-new',
  },
  // Estados de versões anteriores, para o histórico não sumir da tela.
  saudacao: { label: 'Montando pedido', className: 'bg-status-new-bg text-status-new' },
  escolhendo_produto: {
    label: 'Montando pedido',
    className: 'bg-status-new-bg text-status-new',
  },
  personalizando_item: {
    label: 'Montando pedido',
    className: 'bg-status-production-bg text-status-production',
  },
  revisando_carrinho: {
    label: 'Montando pedido',
    className: 'bg-status-production-bg text-status-production',
  },
  coletando_endereco: {
    label: 'Montando pedido',
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
