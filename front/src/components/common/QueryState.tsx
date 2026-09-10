/**
 * Estados de carregamento, erro e vazio.
 *
 * Existe porque cada gráfico do dashboard precisa dos três, e repetir isso em
 * quatro componentes é como o front acabava mostrando um gráfico vazio sem
 * dizer se não havia venda ou se a API caiu.
 */

import { AlertTriangle, Inbox, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

interface QueryErrorProps {
  error: unknown;
  onRetry?: () => void;
  className?: string;
  title?: string;
}

/** Mensagem acionável: diz o que houve e oferece o botão de tentar de novo. */
export function QueryError({ error, onRetry, className, title }: QueryErrorProps) {
  const message =
    error instanceof Error && error.message
      ? error.message
      : 'Não foi possível carregar os dados.';

  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center',
        className,
      )}
    >
      <AlertTriangle className="h-6 w-6 text-destructive" />
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title ?? 'Falha ao carregar'}</p>
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="gap-2">
          <RefreshCw className="h-4 w-4" />
          Tentar de novo
        </Button>
      )}
    </div>
  );
}

interface EmptyStateProps {
  message: string;
  hint?: string;
  className?: string;
}

export function EmptyState({ message, hint, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground',
        className,
      )}
    >
      <Inbox className="h-6 w-6 opacity-60" />
      <p className="text-sm">{message}</p>
      {hint && <p className="text-xs opacity-80">{hint}</p>}
    </div>
  );
}

interface QueryStateProps {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  isEmpty?: boolean;
  emptyMessage?: string;
  emptyHint?: string;
  onRetry?: () => void;
  /** Altura reservada para não haver salto de layout entre skeleton e gráfico. */
  className?: string;
  children: React.ReactNode;
}

/**
 * Decide entre skeleton, erro, vazio e conteúdo. Devolve `children` só quando
 * há dados de verdade.
 */
export function QueryState({
  isLoading,
  isError,
  error,
  isEmpty,
  emptyMessage = 'Nada por aqui ainda.',
  emptyHint,
  onRetry,
  className,
  children,
}: QueryStateProps) {
  if (isLoading) {
    return <Skeleton className={cn('h-full w-full rounded-lg', className)} />;
  }
  if (isError) {
    return <QueryError error={error} onRetry={onRetry} className={cn('h-full', className)} />;
  }
  if (isEmpty) {
    return (
      <EmptyState message={emptyMessage} hint={emptyHint} className={cn('h-full', className)} />
    );
  }
  return <>{children}</>;
}
