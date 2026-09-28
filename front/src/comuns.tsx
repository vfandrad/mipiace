/**
 * As pecas que todas as telas usam: moldura da pagina, cabecalho com as abas,
 * estados de carregando/erro/vazio, botao de recarregar e lista arrastavel.
 */

import { STORE_LOGO_URL, STORE_NAME } from '@/api';
import type { ReactNode } from 'react';
import { cn } from '@/formato';
import { useLayoutEffect, useCallback, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { BarChart3, MessageSquare, Package, Store, AlertTriangle, Inbox, RefreshCw, GripVertical } from 'lucide-react';
import { Button } from '@/ui';
import { Skeleton } from '@/ui';
import { DndContext, KeyboardSensor, PointerSensor, TouchSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

// ---------------------------------------------------------------
// StoreMark
// ---------------------------------------------------------------

export function StoreMark() {
  if (!STORE_LOGO_URL) {
    return (
      <span className="truncate text-lg font-semibold tracking-tight sm:text-xl">
        {STORE_NAME}
      </span>
    );
  }
  return (
    <img src={STORE_LOGO_URL} alt={STORE_NAME} className="h-8 object-contain sm:h-10" />
  );
}

// ---------------------------------------------------------------
// Page
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// Header
// ---------------------------------------------------------------

const NAV_ITEMS = [
  { path: '/producao', label: 'Produção', icon: Store },
  { path: '/produtos', label: 'Produtos', icon: Package },
  { path: '/conversas', label: 'Conversas', icon: MessageSquare },
  { path: '/dashboard', label: 'Dashboard', icon: BarChart3 },
];

export function Header() {
  const { pathname } = useLocation();
  const navRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);

  const activeIndex = NAV_ITEMS.findIndex(item => item.path === pathname);

  // Calcula posição do indicador com base no botão ativo
  const updateIndicator = useCallback(() => {
    if (activeIndex === -1 || !navRef.current) {
      setIndicator(null);
      return;
    }
    const btn = itemRefs.current[activeIndex];
    if (!btn) return;

    const navRect = navRef.current.getBoundingClientRect();
    const btnRect = btn.getBoundingClientRect();
    setIndicator({ left: btnRect.left - navRect.left, width: btnRect.width });
  }, [activeIndex]);

  // Recalcula ao mudar rota ou ao redimensionar
  useLayoutEffect(() => {
    updateIndicator();
    const observer = new ResizeObserver(updateIndicator);
    if (navRef.current) observer.observe(navRef.current);
    return () => observer.disconnect();
  }, [updateIndicator]);

  return (
    // pt-safe: com viewport-fit=cover a pagina entra por baixo da barra de
    // status do iPhone, e o header grudado no topo ficaria atras do notch.
    <header className="sticky top-0 z-50 w-full border-b border-border bg-card/80 backdrop-blur-sm pt-safe">
      <div className="container flex h-16 items-center justify-between gap-2">
        <Link to="/" className="flex shrink-0 items-center gap-2">
          <StoreMark />
        </Link>

        <nav ref={navRef} className="relative flex shrink-0 items-center bg-secondary rounded-lg p-1">
          {/* Indicador deslizante */}
          {indicator && (
            <div
              className="absolute top-1 bottom-1 rounded-md bg-primary shadow-sm transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)]"
              style={{ left: indicator.left, width: indicator.width }}
            />
          )}

          {NAV_ITEMS.map((item, i) => {
            const Icon = item.icon;
            const isActive = pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                ref={el => { itemRefs.current[i] = el; }}
                className={cn(
                  // min-h/min-w de 44px é o alvo de toque mínimo da Apple: no
                  // celular o rótulo some e sobra só o ícone, que sem isto
                  // ficava com ~32px e errava o dedo.
                  'relative z-10 flex min-h-11 min-w-11 items-center justify-center gap-2 px-3 sm:px-4 py-2 rounded-md text-sm font-medium transition-colors duration-200',
                  isActive ? 'text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
                )}
                aria-label={item.label}
              >
                <Icon className="h-4 w-4" />
                <span className="hidden sm:inline">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------
// QueryState
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// RefreshButton
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// SortableList
// ---------------------------------------------------------------

interface SortableListProps<T extends { id: string }> {
  items: T[];
  /** Recebe a lista já na ordem nova. */
  onReorder: (ids: string[]) => void;
  children: (item: T, handle: ReactNode) => ReactNode;
  className?: string;
  disabled?: boolean;
}

interface RowProps {
  id: string;
  disabled?: boolean;
  children: (handle: ReactNode) => ReactNode;
}

function Row({ id, disabled, children }: RowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });

  // `setNodeRef` vai no item inteiro (é o retângulo que o dnd-kit mede para
  // saber sobre quem você está passando) e `setActivatorNodeRef` na alça (o
  // que inicia o arrasto). Trocar os dois faz o item ser medido do tamanho do
  // ícone ⠿, e aí nenhuma colisão é detectada: arrastar não faz nada.
  const handle = (
    <button
      type="button"
      ref={setActivatorNodeRef}
      {...attributes}
      {...listeners}
      aria-label="Arrastar para reordenar"
      className={cn(
        'flex h-11 w-8 shrink-0 cursor-grab touch-none items-center justify-center',
        'text-muted-foreground/60 hover:text-foreground active:cursor-grabbing sm:h-9',
        disabled && 'pointer-events-none opacity-30',
      )}
    >
      <GripVertical className="h-4 w-4" />
    </button>
  );

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(isDragging && 'relative z-10 opacity-80 shadow-lg')}
    >
      {children(handle)}
    </div>
  );
}

export function SortableList<T extends { id: string }>({
  items,
  onReorder,
  children,
  className,
  disabled,
}: SortableListProps<T>) {
  const sensors = useSensors(
    // A distância mínima evita que um toque parado vire arrasto de 1px.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = items.findIndex((i) => i.id === active.id);
    const to = items.findIndex((i) => i.id === over.id);
    if (from < 0 || to < 0) return;
    onReorder(arrayMove(items, from, to).map((i) => i.id));
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      modifiers={[restrictToVerticalAxis, restrictToParentElement]}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={items.map((i) => i.id)} strategy={verticalListSortingStrategy}>
        <div className={className}>
          {items.map((item) => (
            <Row key={item.id} id={item.id} disabled={disabled}>
              {(handle) => children(item, handle)}
            </Row>
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
