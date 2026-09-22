/**
 * Conversas — monitoramento do agente de WhatsApp.
 *
 * Lista à esquerda, chat à direita. O botão de handoff é o "assumir
 * atendimento": com `handoff=true` o runner do agente para de responder e o
 * lojista fala pelo WhatsApp normalmente.
 */

import { useEffect, useMemo, useState } from 'react';
import { Bot, Hand, RefreshCw } from 'lucide-react';
import { Header } from '@/components/layout/Header';
import { Button } from '@/components/ui/button';
import { ConversationList } from '@/components/conversas/ConversationList';
import { ConversationStateBadge } from '@/components/conversas/ConversationStateBadge';
import { MessageThread } from '@/components/conversas/MessageThread';
import { EmptyState } from '@/components/common/QueryState';
import {
  useConversationMessages,
  useConversations,
  useHandoffMutation,
} from '@/hooks/use-conversations';
import { formatPhone, formatRelative } from '@/lib/format';

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
    <div className="min-h-screen-safe bg-background">
      <Header />
      <main className="container py-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))] space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Conversas</h1>
            <p className="text-muted-foreground">
              Acompanhe o agente de WhatsApp e assuma o atendimento quando quiser
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => {
              conversationsQuery.refetch();
              messagesQuery.refetch();
            }}
          >
            <RefreshCw className="h-4 w-4" />
            Atualizar
          </Button>
        </div>

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
      </main>
    </div>
  );
};

export default Conversas;
