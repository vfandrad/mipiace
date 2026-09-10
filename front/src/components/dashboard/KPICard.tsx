/**
 * Card de indicador: valor grande + variação percentual opcional.
 */

import { TrendingDown, TrendingUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatPercent } from '@/lib/format';

interface KPICardProps {
  title: string;
  /** Já formatado por quem chama (moeda, inteiro, ...). */
  value: string | number;
  /** Variação percentual; omitir esconde o rodapé. */
  change?: number;
  changeLabel?: string;
  icon?: React.ReactNode;
  className?: string;
}

export function KPICard({ title, value, change, changeLabel, icon, className }: KPICardProps) {
  const isPositive = typeof change === 'number' && change > 0;
  const isNegative = typeof change === 'number' && change < 0;

  return (
    <div className={cn('kpi-card animate-fade-in', className)}>
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <p className="text-3xl font-semibold tracking-tight">
            {typeof value === 'number' ? value.toLocaleString('pt-BR') : value}
          </p>
        </div>
        {icon && <div className="p-2 rounded-lg bg-secondary">{icon}</div>}
      </div>

      {change !== undefined && (
        <div className="mt-4 flex items-center gap-2">
          <div
            className={cn(
              'flex items-center gap-1 text-sm font-medium',
              isPositive && 'text-status-ready',
              isNegative && 'text-destructive',
              !isPositive && !isNegative && 'text-muted-foreground',
            )}
          >
            {isPositive && <TrendingUp className="h-4 w-4" />}
            {isNegative && <TrendingDown className="h-4 w-4" />}
            <span>{formatPercent(change)}</span>
          </div>
          {changeLabel && <span className="text-sm text-muted-foreground">{changeLabel}</span>}
        </div>
      )}
    </div>
  );
}
