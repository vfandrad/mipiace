/**
 * Filtro de período do dashboard.
 *
 * Componente controlado de propósito: o período mora no Admin e vai para a
 * queryKey das métricas, então clicar aqui realmente refaz a busca na API.
 */

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { MetricsRange } from '@/types/metrics';

const PERIODS: { value: MetricsRange; label: string }[] = [
  { value: 'hoje', label: 'Hoje' },
  { value: 'semana', label: 'Semana' },
  { value: 'mes', label: 'Mês' },
];

interface DateFilterProps {
  value: MetricsRange;
  onChange: (range: MetricsRange) => void;
}

export function DateFilter({ value, onChange }: DateFilterProps) {
  return (
    <div className="flex items-center bg-secondary rounded-lg p-1" role="group" aria-label="Período">
      {PERIODS.map((option) => (
        <Button
          key={option.value}
          variant="ghost"
          size="sm"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            value === option.value
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}
