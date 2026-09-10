/**
 * Produtos — cardápio no padrão PDV.
 * Hierarquia: Produto (card) > Categoria/Grupo > Complementos.
 *
 * A árvore já vem aninhada de `GET /api/products`; as escritas usam as rotas
 * aninhadas (`/api/products/{id}/groups`, `/api/groups/{id}/complements`).
 */

import { useState } from 'react';
import { FolderPlus, Pencil, Trash2 } from 'lucide-react';
import { Header } from '@/components/layout/Header';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { EmptyState, QueryError } from '@/components/common/QueryState';
import { useProducts } from '@/hooks/use-products';
import { formatCurrency } from '@/lib/format';
import type { CatalogEntity, Complement, Product } from '@/types/catalog';
import { ProductsHeader } from '@/components/products/ProductsHeader';
import { GroupCard } from '@/components/products/GroupCard';
import { CreateProductDialog } from '@/components/products/CreateProductDialog';
import { CreateGroupDialog } from '@/components/products/CreateGroupDialog';
import { CreateComplementDialog } from '@/components/products/CreateComplementDialog';
import { EditItemSheet } from '@/components/products/EditItemSheet';
import { DeleteConfirmDialog } from '@/components/products/DeleteConfirmDialog';

const Produtos = () => {
  const catalog = useProducts();
  const { products, isLoading, isError, error } = catalog;

  const [showNewProduct, setShowNewProduct] = useState(false);
  const [newGroupProduct, setNewGroupProduct] = useState<{ id: string; name: string } | null>(null);
  const [newComplementGroupId, setNewComplementGroupId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<{
    type: 'product' | 'complement';
    item: Product | Complement;
  } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{
    entity: CatalogEntity;
    id: string;
    name: string;
    cascadeWarning?: boolean;
  } | null>(null);

  const handleDelete = () => {
    if (!deleteTarget) return;
    catalog.deleteItem(deleteTarget.entity, deleteTarget.id);
    setDeleteTarget(null);
  };

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="container py-6 space-y-6">
        <ProductsHeader onNewProduct={() => setShowNewProduct(true)} />

        {isError ? (
          <QueryError
            error={error}
            onRetry={() => catalog.refetch()}
            title="Não foi possível carregar o cardápio"
          />
        ) : isLoading ? (
          <div className="space-y-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        ) : products.length === 0 ? (
          <EmptyState
            message="Nenhum produto cadastrado."
            hint='Comece criando um produto em "Novo Produto".'
            className="border border-dashed rounded-lg py-12"
          />
        ) : (
          <div className="space-y-6">
            {products.map((product) => (
              <Card key={product.id} className={product.is_available ? undefined : 'opacity-70'}>
                <CardHeader>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <CardTitle className="text-xl truncate">{product.name}</CardTitle>
                      <Badge variant="secondary">{formatCurrency(product.base_price)}</Badge>
                      {!product.is_available && <Badge variant="outline">Indisponível</Badge>}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
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
                        aria-label={`Editar ${product.name}`}
                        onClick={() => setEditTarget({ type: 'product', item: product })}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Excluir ${product.name}`}
                        onClick={() =>
                          setDeleteTarget({
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
                  {product.groups.map((group) => (
                    <GroupCard
                      key={group.id}
                      group={group}
                      isSaving={catalog.isSaving}
                      onToggleComplement={(complement) =>
                        catalog.toggleAvailability(
                          'complement',
                          complement.id,
                          !complement.is_available,
                        )
                      }
                      onEditComplement={(complement) =>
                        setEditTarget({ type: 'complement', item: complement })
                      }
                      onDeleteComplement={(complement) =>
                        setDeleteTarget({
                          entity: 'complement',
                          id: complement.id,
                          name: complement.name,
                        })
                      }
                      onDeleteGroup={() =>
                        setDeleteTarget({
                          entity: 'group',
                          id: group.id,
                          name: group.name,
                          cascadeWarning: group.complements.length > 0,
                        })
                      }
                      onAddComplement={() => setNewComplementGroupId(group.id)}
                    />
                  ))}

                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={() => setNewGroupProduct({ id: product.id, name: product.name })}
                  >
                    <FolderPlus className="h-4 w-4 mr-2" />
                    Nova categoria para "{product.name}"
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Diálogos */}
        <CreateProductDialog
          open={showNewProduct}
          onOpenChange={setShowNewProduct}
          onCreate={catalog.createProduct}
        />
        <CreateGroupDialog
          open={!!newGroupProduct}
          onOpenChange={(open) => !open && setNewGroupProduct(null)}
          productId={newGroupProduct?.id ?? ''}
          productName={newGroupProduct?.name ?? ''}
          onCreate={catalog.createGroup}
        />
        <CreateComplementDialog
          open={!!newComplementGroupId}
          onOpenChange={(open) => !open && setNewComplementGroupId(null)}
          groupId={newComplementGroupId ?? ''}
          onCreate={catalog.createComplement}
        />
        <EditItemSheet
          editTarget={editTarget}
          onClose={() => setEditTarget(null)}
          onSave={catalog.editItem}
        />
        <DeleteConfirmDialog
          open={!!deleteTarget}
          name={deleteTarget?.name ?? ''}
          cascadeWarning={deleteTarget?.cascadeWarning}
          onOpenChange={(open) => !open && setDeleteTarget(null)}
          onConfirm={handleDelete}
        />
      </main>
    </div>
  );
};

export default Produtos;
