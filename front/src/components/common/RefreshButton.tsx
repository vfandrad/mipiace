/**
 * Botão "Atualizar" — o mesmo nas quatro telas.
 *
 * Existia só em Conversas, com aparência própria. Ter um componente evita que
 * cada tela invente o seu e garante o detalhe que faz o botão parecer vivo: o
 * ícone gira enquanto a requisição está no ar. Sem isso, clicar num painel que
 * já estava atualizado não dá retorno nenhum e parece que o botão não funciona.
 */

import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface Props {
  /** Refaz as consultas da tela. Pode devolver promessa ou nada. */
  onRefresh: () => unknown;
  className?: string;
}

/** Giro mínimo, para o clique ter resposta visível mesmo em rede rápida. */
const MIN_SPIN_MS = 600;

export function RefreshButton({ onRefresh, className }: Props) {
  const [spinning, setSpinning] = useState(false);

  const handle = async () => {
    if (spinning) return;
    setSpinning(true);
    const started = Date.now();
    try {
      await onRefresh();
    } finally {
      const elapsed = Date.now() - started;
      setTimeout(() => setSpinning(false), Math.max(0, MIN_SPIN_MS - elapsed));
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className={cn('min-h-11 gap-2 sm:min-h-9', className)}
      onClick={handle}
      disabled={spinning}
      aria-label="Atualizar"
    >
      <RefreshCw className={cn('h-4 w-4', spinning && 'animate-spin')} />
      Atualizar
    </Button>
  );
}
