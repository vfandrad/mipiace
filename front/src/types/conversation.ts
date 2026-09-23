/**
 * Tipos da tela de monitoramento do agente de WhatsApp.
 * Os estados espelham `back/app/domain/enums.py::ConversationState`.
 */

export const CONVERSATION_STATES = [
  'conversando',
  'confirmando_pedido',
  'aguardando_pagamento',
  'concluido',
  'atendimento_humano',
  'cancelado',
] as const;

export type ConversationState = (typeof CONVERSATION_STATES)[number];

export type MessageDirection = 'entrada' | 'saida';

export interface Conversation {
  id: string;
  phone: string;
  /** String livre no banco; tratamos valores desconhecidos sem quebrar a tela. */
  state: ConversationState | string;
  handoff: boolean;
  channel?: string;
  customer_name?: string | null;
  last_message_at?: string | null;
  last_message_preview?: string | null;
  active_order_id?: string | null;
  fail_count?: number;
}

export interface ConversationMessage {
  id?: string;
  direction: MessageDirection;
  content: string;
  detected_intent?: string | null;
  state_before?: string | null;
  state_after?: string | null;
  created_at: string;
}
