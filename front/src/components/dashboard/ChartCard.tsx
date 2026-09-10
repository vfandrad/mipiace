/**
 * Moldura comum dos gráficos: título + área de altura fixa que sabe mostrar
 * skeleton, erro com botão de tentar de novo, ou "ainda não há vendas".
 */

import { QueryState } from '@/components/common/QueryState';

interface ChartCardProps {
  title: string;
  subtitle?: string;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  isEmpty: boolean;
  emptyMessage: string;
  onRetry?: () => void;
  children: React.ReactNode;
}

export function ChartCard({
  title,
  subtitle,
  isLoading,
  isError,
  error,
  isEmpty,
  emptyMessage,
  onRetry,
  children,
}: ChartCardProps) {
  return (
    <div className="kpi-card">
      <div className="mb-4">
        <h3 className="font-semibold text-sm sm:text-base">{title}</h3>
        {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
      </div>
      <div className="h-[200px] sm:h-[280px]">
        <QueryState
          isLoading={isLoading}
          isError={isError}
          error={error}
          isEmpty={isEmpty}
          emptyMessage={emptyMessage}
          onRetry={onRetry}
        >
          {children}
        </QueryState>
      </div>
    </div>
  );
}

/** Estilo compartilhado das tooltips do Recharts (segue os tokens do tema). */
export const TOOLTIP_STYLE = {
  backgroundColor: 'hsl(var(--card))',
  border: '1px solid hsl(var(--border))',
  borderRadius: '8px',
  fontSize: '12px',
} as const;

export const AXIS_TICK = { fill: 'hsl(var(--muted-foreground))', fontSize: 11 } as const;
