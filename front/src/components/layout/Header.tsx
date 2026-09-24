/**
 * Header com navegação e indicador deslizante animado
 */

import { useLayoutEffect, useCallback, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { BarChart3, MessageSquare, Package, Store } from 'lucide-react';
import { StoreMark } from '@/components/layout/StoreMark';

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
