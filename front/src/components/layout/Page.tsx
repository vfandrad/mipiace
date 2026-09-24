/**
 * A moldura de toda tela do painel: cabeçalho + `<main>` no container.
 *
 * Existe porque as quatro páginas repetiam este trecho byte a byte, incluindo
 * o `pb-[calc(...env(safe-area-inset-bottom))]` que impede o rodapé de ficar
 * atrás da barra de gestos do iPhone — o tipo de detalhe que uma cópia nova
 * esquece. Não é abstração antecipada: é a quinta cópia que não vai existir.
 */

import type { ReactNode } from 'react';
import { Header } from '@/components/layout/Header';
import { cn } from '@/lib/utils';

interface PageProps {
  children: ReactNode;
  /** Espaçamento entre os blocos da página; algumas telas controlam o seu. */
  className?: string;
}

export function Page({ children, className }: PageProps) {
  return (
    <div className="min-h-screen-safe bg-background">
      <Header />
      <main
        className={cn(
          'container py-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))]',
          className,
        )}
      >
        {children}
      </main>
    </div>
  );
}

interface PageTitleProps {
  title: string;
  subtitle?: string;
  /** Botões à direita — empilham abaixo do título no celular. */
  actions?: ReactNode;
}

/** Título da tela com as ações ao lado. Também era o mesmo em quatro lugares. */
export function PageTitle({ title, subtitle, actions }: PageTitleProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
