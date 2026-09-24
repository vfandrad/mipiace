/**
 * O card de um produto: nome, preço, disponibilidade e os grupos de opções.
 *
 * Era um bloco de ~120 linhas escrito dentro do render-prop do `SortableList`
 * em `Produtos.tsx` — um componente em tudo menos no nome, ao lado do
 * `GroupCard` que já tinha sido extraído. A página encolheu de 405 para pouco
 * mais de 280 linhas e voltou a caber na cabeça: ela cuida de busca, seleção
 * em massa e diálogos; o card cuida de um produto.
 *
 * Recebe o `catalog` inteiro de propósito. O card dispara meia dúzia de
 * operações do cardápio (disponibilidade, reordenar grupos, reordenar itens) e
 * repassar cada uma como prop própria só trocaria seis linhas por seis linhas,
 * sem ninguém ganhar clareza.
 */

import type { ReactNode } from 'react';
import { FolderPlus, Pencil, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { SortableList } from '@/components/common/SortableList';
import { GroupCard } from '@/components/produtos/GroupCard';
import type { EditTarget } from '@/components/produtos/EditItemSheet';
import type { useProducts } from '@/hooks/use-products';
import { formatCurrency } from '@/lib/format';
import type { CatalogEntity, ComplementCategory, Product } from '@/types/catalog';

/** O que o diálogo de exclusão precisa saber sobre o alvo. */
export interface DeleteTarget {
  entity: CatalogEntity;
  id: string;
  name: string;
  cascadeWarning?: boolean;
  usageNote?: string;
}

interface Props {
  product: Product;
  catalog: ReturnType<typeof useProducts>;
  categories: ComplementCategory[];
  /** Alça de arrasto do produto; ausente enquanto há busca ativa. */
  dragHandle?: ReactNode;
  /** Termo de busca — com filtro, arrastar é desligado e os grupos abrem. */
  filtro: string;
  selecionados: Set<string>;
  onToggleSelecao: (id: string) => void;
  onSelecionarGrupo: (ids: string[], marcar: boolean) => void;
  onEdit: (target: EditTarget) => void;
  onDelete: (target: DeleteTarget) => void;
  onNewGroup: (product: { id: string; name: string }) => void;
  onNewComplement: (groupId: string) => void;
}

export const ProductCard = ({
  product,
  catalog,
  categories,
  dragHandle,
  filtro,
  selecionados,
  onToggleSelecao,
  onSelecionarGrupo,
  onEdit,
  onDelete,
  onNewGroup,
  onNewComplement,
}: Props) => (
  <Card className={product.is_available ? undefined : 'opacity-70'}>
    {/* Nome e preço em cima, controles ao lado: numa faixa de 390px, nome +
        preço + interruptor + dois botões na mesma linha não cabem, e o título
        era o primeiro a ser cortado. */}
    <CardHeader className="pb-3">
      <div className="flex items-start justify-between gap-2">
        {dragHandle && <div className="pt-1">{dragHandle}</div>}
        <div className="min-w-0 flex-1">
          <CardTitle className="truncate text-lg sm:text-xl">{product.name}</CardTitle>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{formatCurrency(product.base_price)}</Badge>
            {!product.is_available && <Badge variant="outline">Indisponível</Badge>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Switch
            checked={product.is_available}
            aria-label={`Disponibilidade de ${product.name}`}
            onCheckedChange={() =>
              catalog.toggleAvailability('product', product.id, !product.is_available)
            }
            disabled={catalog.isSaving}
          />
          <Button
            variant="ghost"
            size="icon"
            className="h-11 w-11 sm:h-9 sm:w-9"
            aria-label={`Editar ${product.name}`}
            onClick={() => onEdit({ type: 'product', item: product })}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-11 w-11 sm:h-9 sm:w-9"
            aria-label={`Excluir ${product.name}`}
            onClick={() =>
              onDelete({
                entity: 'product',
                id: product.id,
                name: product.name,
                cascadeWarning: product.groups.length > 0,
              })
            }
          >
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      </div>
    </CardHeader>

    <CardContent className="space-y-4">
      <SortableList
        items={product.groups}
        onReorder={(ids) => catalog.reorderGroups(product.id, ids)}
        disabled={Boolean(filtro)}
        className="space-y-4"
      >
        {(group, groupHandle) => (
          <GroupCard
            group={group}
            dragHandle={!filtro ? groupHandle : undefined}
            onReorderComplements={(ids) => catalog.reorderComplements(group.id, ids)}
            categories={categories}
            filtro={filtro}
            selecionados={selecionados}
            onToggleSelecao={onToggleSelecao}
            onSelecionarGrupo={onSelecionarGrupo}
            isSaving={catalog.isSaving}
            onToggleComplement={(complement) =>
              catalog.toggleAvailability(
                'complement',
                complement.id,
                !complement.is_available,
              )
            }
            onEditComplement={(complement) =>
              onEdit({ type: 'complement', item: complement })
            }
            onDeleteComplement={(complement) =>
              onDelete({
                entity: 'complement',
                id: complement.id,
                name: complement.name,
              })
            }
            onEditGroup={() => onEdit({ type: 'group', item: group })}
            onDeleteGroup={() =>
              onDelete({
                entity: 'group',
                id: group.id,
                name: group.name,
                // Sem cascata: os itens são da lista compartilhada e continuam
                // existindo para os outros produtos que a usam.
                usageNote: `Os ${group.complements.length} itens da lista continuam existindo — só deixam de valer para "${product.name}".`,
              })
            }
            // O id da LISTA, não o do vínculo: o complemento entra na lista
            // compartilhada e aparece em todo produto que a usa.
            onAddComplement={() => onNewComplement(group.group_id)}
          />
        )}
      </SortableList>

      <Button
        variant="outline"
        size="sm"
        className="min-h-11 w-full sm:min-h-9"
        onClick={() => onNewGroup({ id: product.id, name: product.name })}
      >
        <FolderPlus className="mr-2 h-4 w-4 shrink-0" />
        <span className="truncate">Novo grupo de opções</span>
      </Button>
    </CardContent>
  </Card>
);
