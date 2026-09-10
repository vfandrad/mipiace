/**
 * Lista lateral de conversas: telefone, estado da máquina e "há quanto tempo".
 */

import { Hand } from 'lucide-react';
import { ConversationStateBadge } from './ConversationStateBadge';
import { EmptyState, QueryError } from '@/components/common/QueryState';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { formatPhone, formatRelative } from '@/lib/format';
import type { Conversation } from '@/types/conversation';

interface Props {
  conversations: Conversation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  onRetry?: () => void;
}

export function ConversationList({
  conversations,
  selectedId,
  onSelect,
  isLoading,
  isError,
  error,
  onRetry,
}: Props) {
  if (isLoading) {
    return (
      <div className="space-y-2 p-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-16 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <QueryError
        error={error}
        onRetry={onRetry}
        title="Não foi possível carregar as conversas"
        className="m-2"
      />
    );
  }

  if (conversations.length === 0) {
    return (
      <EmptyState
        message="Nenhuma conversa ainda."
        hint="Mande uma mensagem pelo simulador para ver o agente trabalhando."
        className="py-12"
      />
    );
  }

  return (
    <ul className="divide-y divide-border">
      {conversations.map((conversation) => (
        <li key={conversation.id}>
          <button
            type="button"
            onClick={() => onSelect(conversation.id)}
            aria-current={selectedId === conversation.id}
            className={cn(
              'w-full text-left px-4 py-3 transition-colors hover:bg-secondary/60',
              selectedId === conversation.id && 'bg-secondary',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium truncate">
                {conversation.customer_name || formatPhone(conversation.phone)}
              </span>
              <span className="text-xs text-muted-foreground shrink-0">
                {formatRelative(conversation.last_message_at)}
              </span>
            </div>
            {conversation.last_message_preview && (
              <p className="mt-0.5 text-xs text-muted-foreground truncate">
                {conversation.last_message_preview}
              </p>
            )}
            <div className="mt-1 flex items-center gap-2 flex-wrap">
              <ConversationStateBadge state={conversation.state} />
              {conversation.handoff && (
                <span className="inline-flex items-center gap-1 text-xs text-destructive font-medium">
                  <Hand className="h-3 w-3" />
                  bot pausado
                </span>
              )}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
