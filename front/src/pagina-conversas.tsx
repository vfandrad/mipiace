/**
 * A tela de Conversas: o historico do que o bot e o cliente disseram.
 *
 * Leitura, mais o botao que passa a conversa para um atendente humano.
 */

import { cn } from '@/formato';
import { Hand, Bot } from 'lucide-react';
import { EmptyState, QueryError } from '@/comuns';
import { Skeleton } from '@/ui';
import { formatPhone, formatRelative, formatDateTime } from '@/formato';
import type { Conversation, ConversationMessage } from '@/tipos';
import { useEffect, useRef, useMemo, useState } from 'react';
import { Page, PageTitle } from '@/comuns';
import { Button } from '@/ui';
import { RefreshButton } from '@/comuns';
import { useConversationMessages, useConversations, useHandoffMutation } from '@/dados';

// ---------------------------------------------------------------
// ConversationStateBadge
// ---------------------------------------------------------------

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

interface PropsConversationstatebadge {
  state: string;
  className?: string;
}

export function ConversationStateBadge({ state, className }: PropsConversationstatebadge) {
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

// ---------------------------------------------------------------
// ConversationList
// ---------------------------------------------------------------

interface PropsConversationlist {
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
}: PropsConversationlist) {
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

// ---------------------------------------------------------------
// MessageThread
// ---------------------------------------------------------------

interface PropsMessagethread {
  messages: ConversationMessage[];
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  onRetry?: () => void;
}

export function MessageThread({ messages, isLoading, isError, error, onRetry }: PropsMessagethread) {
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

// ---------------------------------------------------------------
// Conversas
// ---------------------------------------------------------------

const Conversas = () => {
  const conversationsQuery = useConversations();
  // useMemo evita que a lista vazia vire um array novo a cada render e
  // dispare o efeito de seleção em loop.
  const conversations = useMemo(() => conversationsQuery.data ?? [], [conversationsQuery.data]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Seleciona a primeira conversa assim que a lista chega, para a tela não
  // nascer vazia; se a selecionada sumir, volta a não ter seleção.
  useEffect(() => {
    if (conversations.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !conversations.some((c) => c.id === selectedId)) {
      setSelectedId(conversations[0].id);
    }
  }, [conversations, selectedId]);

  const selected = conversations.find((c) => c.id === selectedId) ?? null;
  const messagesQuery = useConversationMessages(selectedId);
  const handoff = useHandoffMutation();

  return (
    <Page className="space-y-4">
      <PageTitle
        title="Conversas"
        subtitle="Acompanhe o agente de WhatsApp e assuma o atendimento quando quiser"
        actions={
          <RefreshButton
            onRefresh={() =>
              Promise.all([conversationsQuery.refetch(), messagesQuery.refetch()])
            }
          />
        }
      />

        <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4">
          {/* Lista */}
          <aside className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <h2 className="text-sm font-semibold">
                {conversations.length} conversa{conversations.length === 1 ? '' : 's'}
              </h2>
              <p className="text-xs text-muted-foreground">Atualiza sozinho a cada 10s</p>
            </div>
            <div className="max-h-[45dvh] lg:max-h-[70dvh] overflow-y-auto scrollbar-thin">
              <ConversationList
                conversations={conversations}
                selectedId={selectedId}
                onSelect={setSelectedId}
                isLoading={conversationsQuery.isLoading}
                isError={conversationsQuery.isError}
                error={conversationsQuery.error}
                onRetry={() => conversationsQuery.refetch()}
              />
            </div>
          </aside>

          {/* Chat */}
          <section className="rounded-lg border border-border bg-secondary/30 overflow-hidden flex flex-col min-h-[420px]">
            {!selected ? (
              <EmptyState
                message="Selecione uma conversa para ver o histórico."
                className="flex-1"
              />
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-border bg-card">
                  <div className="min-w-0">
                    <p className="font-semibold truncate">{formatPhone(selected.phone)}</p>
                    <div className="mt-1 flex items-center gap-2 flex-wrap">
                      <ConversationStateBadge state={selected.state} />
                      <span className="text-xs text-muted-foreground">
                        última mensagem {formatRelative(selected.last_message_at)}
                      </span>
                    </div>
                  </div>
                  <Button
                    variant={selected.handoff ? 'default' : 'outline'}
                    size="sm"
                    className="gap-2"
                    disabled={handoff.isPending}
                    onClick={() =>
                      handoff.mutate({ id: selected.id, handoff: !selected.handoff })
                    }
                  >
                    {selected.handoff ? (
                      <>
                        <Bot className="h-4 w-4" />
                        Devolver ao bot
                      </>
                    ) : (
                      <>
                        <Hand className="h-4 w-4" />
                        Assumir atendimento
                      </>
                    )}
                  </Button>
                </div>

                {selected.handoff && (
                  <p className="px-4 py-2 text-xs bg-destructive/10 text-destructive border-b border-destructive/20">
                    O bot está pausado nesta conversa: responda pelo WhatsApp normalmente.
                  </p>
                )}

                <div className="flex-1 overflow-y-auto scrollbar-thin max-h-[55dvh] lg:max-h-[62dvh]">
                  <MessageThread
                    messages={messagesQuery.data ?? []}
                    isLoading={messagesQuery.isLoading}
                    isError={messagesQuery.isError}
                    error={messagesQuery.error}
                    onRetry={() => messagesQuery.refetch()}
                  />
                </div>
              </>
            )}
          </section>
        </div>
    </Page>
  );
};

export default Conversas;
