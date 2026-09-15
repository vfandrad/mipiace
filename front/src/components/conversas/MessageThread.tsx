/**
 * Histórico de uma conversa em formato de chat.
 *
 * Entrada (cliente) à esquerda, saída (agente) à direita. Cada mensagem do
 * cliente mostra a intenção que a IA detectou — é o que permite depurar por que
 * o agente respondeu o que respondeu.
 */

import { useEffect, useRef } from 'react';
import { EmptyState, QueryError } from '@/components/common/QueryState';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { formatDateTime } from '@/lib/format';
import type { ConversationMessage } from '@/types/conversation';

interface Props {
  messages: ConversationMessage[];
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  onRetry?: () => void;
}

export function MessageThread({ messages, isLoading, isError, error, onRetry }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Rola para a última mensagem sempre que o poll trouxer algo novo.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length]);

  if (isLoading) {
    return (
      <div className="space-y-3 p-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className={cn('h-14 w-2/3 rounded-lg', i % 2 === 1 && 'ml-auto')} />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <QueryError
        error={error}
        onRetry={onRetry}
        title="Não foi possível carregar o histórico"
        className="m-4"
      />
    );
  }

  if (messages.length === 0) {
    return <EmptyState message="Nenhuma mensagem nesta conversa." className="py-16" />;
  }

  return (
    <div className="space-y-3 p-4">
      {messages.map((message, index) => {
        const isInbound = message.direction === 'entrada';
        return (
          <div
            key={message.id ?? `${message.created_at}-${index}`}
            className={cn('flex', isInbound ? 'justify-start' : 'justify-end')}
          >
            <div
              className={cn(
                'max-w-[80%] rounded-lg px-3 py-2 shadow-sm',
                isInbound
                  ? 'bg-card border border-border'
                  : 'bg-primary text-primary-foreground',
              )}
            >
              <p className="whitespace-pre-wrap text-sm break-words">{message.content}</p>
              <div
                className={cn(
                  'mt-1 flex items-center gap-2 text-[10px]',
                  isInbound ? 'text-muted-foreground' : 'text-primary-foreground/70',
                )}
              >
                <span>{formatDateTime(message.created_at)}</span>
                {isInbound && message.detected_intent && (
                  <span className="inline-flex items-center rounded bg-secondary px-1.5 py-0.5 font-medium text-secondary-foreground">
                    {message.detected_intent.replace(/_/g, ' ')}
                  </span>
                )}
                {!isInbound && message.state_after && (
                  <span className="inline-flex items-center rounded bg-primary-foreground/15 px-1.5 py-0.5 font-medium">
                    → {message.state_after.replace(/_/g, ' ')}
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
