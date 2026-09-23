/**
 * Produtos — cardápio no padrão PDV.
 * Hierarquia: Produto (card) > Categoria/Grupo > Complementos.
 *
 * A árvore já vem aninhada de `GET /api/products`; as escritas usam as rotas
 * aninhadas (`/api/products/{id}/groups`, `/api/groups/{id}/complements`).
 */

import { useMemo, useState } from 'react';
import { CheckCircle2, FolderPlus, Pencil, Search, Trash2, XCircle } from 'lucide-react';
import { Header } from '@/components/layout/Header';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { EmptyState, QueryError } from '@/components/common/QueryState';
import { useProducts } from '@/hooks/use-products';
import { formatCurrency } from '@/lib/format';
import type { CatalogEntity } from '@/types/catalog';
import { ProductsHeader } from '@/components/produtos/ProductsHeader';
import { GroupCard } from '@/components/produtos/GroupCard';
import { CreateProductDialog } from '@/components/produtos/CreateProductDialog';
import { CreateGroupDialog } from '@/components/produtos/CreateGroupDialog';
import { CreateComplementDialog } from '@/components/produtos/CreateComplementDialog';
import { EditItemSheet, type EditTarget } from '@/components/produtos/EditItemSheet';
import { FlavorCategoriesDialog } from '@/components/produtos/FlavorCategoriesDialog';
import { DeleteConfirmDialog } from '@/components/produtos/DeleteConfirmDialog';

const Produtos = () => {
  const catalog = useProducts();
  const { products, flavorCategories, isLoading, isError, error } = catalog;

  const [filtro, setFiltro] = useState('');
  // Edição em massa: ids dos complementos marcados. Um Set porque a operação
  // que mais roda é "está marcado?", uma vez por linha em cada render.
  const [selecionados, setSelecionados] = useState<Set<string>>(new Set());
  const [showNewProduct, setShowNewProduct] = useState(false);
  const [newGroupProduct, setNewGroupProduct] = useState<{ id: string; name: string } | null>(null);
  const [newComplementGroupId, setNewComplementGroupId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
  const [showCategories, setShowCategories] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{
    entity: CatalogEntity;
    id: string;
    name: string;
    cascadeWarning?: boolean;
    usageNote?: string;
  } | null>(null);

  // Buscar sabor pelo nome. São 31 por tamanho, repetidos nos três tamanhos:
  // sem busca, achar "pistache" no celular é rolar 93 linhas. Produto e
  // categoria sem nenhum item correspondente somem enquanto o filtro está
  // ativo, para a tela mostrar só o que a busca encontrou.
  const termo = filtro.trim().toLowerCase();
  const visiveis = useMemo(() => {
    if (!termo) return products;
    return products
      .map((product) => ({
        ...product,
        groups: product.groups
          .map((group) => ({
            ...group,
            complements: group.complements.filter((c) =>
              c.name.toLowerCase().includes(termo),
            ),
          }))
          .filter((group) => group.complements.length > 0),
      }))
      .filter(
        (product) =>
          product.groups.length > 0 || product.name.toLowerCase().includes(termo),
      );
  }, [products, termo]);

  // Quantos sabores usam cada categoria — o diálogo avisa antes de excluir.
  const usoDasCategorias = useMemo(() => {
    const contagem: Record<string, number> = {};
    for (const product of products) {
      for (const group of product.groups) {
        for (const complement of group.complements) {
          const id = complement.flavor_category_id;
          if (id) contagem[id] = (contagem[id] ?? 0) + 1;
        }
      }
    }
    return contagem;
  }, [products]);

  const alternarSelecao = (id: string) =>
    setSelecionados((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(id)) proximo.delete(id);
      else proximo.add(id);
      return proximo;
    });

  const selecionarGrupo = (ids: string[], marcar: boolean) =>
    setSelecionados((atual) => {
      const proximo = new Set(atual);
      ids.forEach((id) => (marcar ? proximo.add(id) : proximo.delete(id)));
      return proximo;
    });

  // Liga ou desliga tudo que está marcado. Vai uma requisição por item: o
  // backend só tem PATCH por complemento, e para a dezena de sabores que o
  // lojista mexe por dia isso é mais simples do que inventar uma rota em lote.
  const aplicarEmMassa = (disponivel: boolean) => {
    selecionados.forEach((id) =>
      catalog.toggleAvailability('complement', id, disponivel),
    );
    setSelecionados(new Set());
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    catalog.deleteItem(deleteTarget.entity, deleteTarget.id);
    setDeleteTarget(null);
  };

  return (
    <div className="min-h-screen-safe bg-background">
      <Header />
      <main className="container py-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))] space-y-6">
        <ProductsHeader
          onNewProduct={() => setShowNewProduct(true)}
          onManageCategories={() => setShowCategories(true)}
          onRefresh={() => catalog.refetch()}
        />

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
            placeholder="Buscar sabor ou produto..."
            aria-label="Buscar no cardápio"
            className="h-12 pl-9 sm:h-10"
          />
        </div>

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
        ) : visiveis.length === 0 ? (
          <EmptyState
            message={termo ? `Nada encontrado para "${filtro}".` : 'Nenhum produto cadastrado.'}
            hint={
              termo
                ? 'Tente outro termo ou limpe a busca.'
                : 'Comece criando um produto em "Novo Produto".'
            }
            className="border border-dashed rounded-lg py-12"
          />
        ) : (
          <div className="space-y-6">
            {visiveis.map((product) => (
              <Card key={product.id} className={product.is_available ? undefined : 'opacity-70'}>
                {/* Nome e preço em cima, controles ao lado: numa faixa de
                    390px, nome + preço + interruptor + dois botões na mesma
                    linha não cabem, e o título era o primeiro a ser cortado. */}
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <CardTitle className="truncate text-lg sm:text-xl">
                        {product.name}
                      </CardTitle>
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
                        onClick={() => setEditTarget({ type: 'product', item: product })}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-11 w-11 sm:h-9 sm:w-9"
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
                      flavorCategories={flavorCategories}
                      filtro={termo}
                      selecionados={selecionados}
                      onToggleSelecao={alternarSelecao}
                      onSelecionarGrupo={selecionarGrupo}
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
                      onEditGroup={() => setEditTarget({ type: 'group', item: group })}
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
                    className="min-h-11 w-full sm:min-h-9"
                    onClick={() => setNewGroupProduct({ id: product.id, name: product.name })}
                  >
                    <FolderPlus className="mr-2 h-4 w-4 shrink-0" />
                    <span className="truncate">Nova categoria</span>
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Barra de edição em massa. Fixa no rodapé porque a seleção acontece
            rolando a lista: um botão no topo sairia da tela justo quando
            passasse a ser útil. */}
        {selecionados.size > 0 && (
          <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] shadow-lg backdrop-blur-sm">
            <div className="container flex flex-wrap items-center gap-2 px-0">
              <span className="text-sm font-medium">
                {selecionados.size} selecionado{selecionados.size === 1 ? '' : 's'}
              </span>
              <div className="ml-auto flex flex-wrap gap-2">
                <Button
                  size="sm"
                  className="min-h-11 gap-2 sm:min-h-9"
                  disabled={catalog.isSaving}
                  onClick={() => aplicarEmMassa(true)}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  Ligar
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  className="min-h-11 gap-2 sm:min-h-9"
                  disabled={catalog.isSaving}
                  onClick={() => aplicarEmMassa(false)}
                >
                  <XCircle className="h-4 w-4" />
                  Desligar
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="min-h-11 sm:min-h-9"
                  onClick={() => setSelecionados(new Set())}
                >
                  Limpar
                </Button>
              </div>
            </div>
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
          flavorCategories={flavorCategories}
          onCreate={catalog.createComplement}
        />
        <FlavorCategoriesDialog
          open={showCategories}
          onOpenChange={setShowCategories}
          categories={flavorCategories}
          usageByCategory={usoDasCategorias}
          onCreate={catalog.createFlavorCategory}
          onRename={(id, data) => catalog.editItem('flavorCategory', id, data)}
          onDelete={(id, name, usage) =>
            setDeleteTarget({
              entity: 'flavorCategory',
              id,
              name,
              // Excluir categoria não apaga sabor: o vínculo vira nulo.
              usageNote:
                usage > 0
                  ? `${usage} ${usage === 1 ? 'sabor perde' : 'sabores perdem'} o agrupamento, mas continuam no cardápio.`
                  : undefined,
            })
          }
        />
        <EditItemSheet
          editTarget={editTarget}
          flavorCategories={flavorCategories}
          onClose={() => setEditTarget(null)}
          onSave={catalog.editItem}
        />
        <DeleteConfirmDialog
          open={!!deleteTarget}
          name={deleteTarget?.name ?? ''}
          cascadeWarning={deleteTarget?.cascadeWarning}
          usageNote={deleteTarget?.usageNote}
          onOpenChange={(open) => !open && setDeleteTarget(null)}
          onConfirm={handleDelete}
        />
      </main>
    </div>
  );
};

export default Produtos;
