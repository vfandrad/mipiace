/**
 * Lista que o lojista reordena arrastando.
 *
 * Substituiu o campo "ordem de exibição": digitar 0, 1, 2 em cada item para
 * decidir o que aparece primeiro é trabalho de planilha, não de cardápio —
 * e ninguém lembra qual número sobrou livre.
 *
 * Três decisões que vale explicar:
 *
 * 1. **A alça é só dela.** Arrastar pelo card inteiro roubaria o toque dos
 *    botões e do interruptor de disponibilidade, que é a ação mais usada da
 *    tela. Só o ícone ⠿ inicia o arrasto.
 * 2. **No celular precisa segurar.** `TouchSensor` com 200ms de espera: sem
 *    isso, rolar a lista com o dedo em cima da alça viraria arrasto.
 * 3. **Teclado funciona.** A alça é focável e as setas movem o item — é de
 *    graça no dnd-kit e é o que torna a tela usável sem mouse.
 */

import type { ReactNode } from 'react';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import { cn } from '@/lib/utils';

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
