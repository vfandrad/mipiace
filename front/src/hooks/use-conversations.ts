/**
 * Monitoramento do agente de WhatsApp.
 *
 * Poll de ~10s: é uma tela de acompanhamento, o lojista precisa ver a mensagem
 * chegar sem apertar F5, e um poll curto é bem mais simples que WebSocket para
 * o volume de um MVP.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { toMillis } from '@/lib/format';
import {
  errorDescription,
  fetchConversationMessages,
  fetchConversations,
  setConversationHandoff,
} from '@/lib/api';
import type { Conversation } from '@/types/conversation';

const POLL_INTERVAL = 10_000;

export const CONVERSATIONS_QUERY_KEY = ['conversations'] as const;

export function useConversations() {
  return useQuery({
    queryKey: CONVERSATIONS_QUERY_KEY,
    queryFn: fetchConversations,
    refetchInterval: POLL_INTERVAL,
    // Mais recente primeiro; conversa sem mensagem vai para o fim.
    select: (rows) =>
      [...(rows ?? [])].sort(
        (a, b) => toMillis(b.last_message_at) - toMillis(a.last_message_at),
      ),
  });
}

export function useConversationMessages(conversationId: string | null) {
  return useQuery({
    queryKey: ['conversations', conversationId, 'messages'],
    queryFn: () => fetchConversationMessages(conversationId as string),
    enabled: Boolean(conversationId),
    refetchInterval: POLL_INTERVAL,
  });
}

/** "Assumir atendimento" (handoff=true) e "devolver ao bot" (handoff=false). */
export function useHandoffMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, handoff }: { id: string; handoff: boolean }) =>
      setConversationHandoff(id, handoff),
    onMutate: async ({ id, handoff }) => {
      await queryClient.cancelQueries({ queryKey: CONVERSATIONS_QUERY_KEY });
      const previous = queryClient.getQueryData<Conversation[]>(CONVERSATIONS_QUERY_KEY);
      queryClient.setQueryData<Conversation[]>(CONVERSATIONS_QUERY_KEY, (old) =>
        old?.map((conversation) =>
          conversation.id === id ? { ...conversation, handoff } : conversation,
        ),
      );
      return { previous };
    },
    onSuccess: (_data, { handoff }) => {
      toast.success(handoff ? 'Bot pausado nesta conversa' : 'Bot retomou o atendimento');
    },
    onError: (error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(CONVERSATIONS_QUERY_KEY, context.previous);
      }
      toast.error('Não foi possível alterar o atendimento', {
        description: errorDescription(error),
      });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: CONVERSATIONS_QUERY_KEY }),
  });
}
