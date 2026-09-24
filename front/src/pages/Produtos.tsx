/**
 * Produtos — cardápio no padrão PDV.
 * Hierarquia: Produto (card) > Categoria/Grupo > Complementos.
 *
 * A árvore já vem aninhada de `GET /api/products`. Um grupo de opções é uma
 * lista compartilhada: o mesmo "Sabores" serve aos três tamanhos de pote, e o
 * que muda por produto é quantas escolhas ele pede. Por isso cada grupo aqui
 * tem dois ids — `id` é o vínculo com ESTE produto (é o que se edita ou se
 * remove) e `group_id` é a lista (é onde os itens entram).
 */

import { useMemo, useState } from 'react';
import { CheckCircle2, Search, XCircle } from 'lucide-react';
import { Page } from '@/components/layout/Page';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { EmptyState, QueryError } from '@/components/common/QueryState';
import { useProducts } from '@/hooks/use-products';
import { ProductsHeader } from '@/components/produtos/ProductsHeader';
import { ProductCard, type DeleteTarget } from '@/components/produtos/ProductCard';
import { CreateProductDialog } from '@/components/produtos/CreateProductDialog';
import { CreateGroupDialog } from '@/components/produtos/CreateGroupDialog';
import { CreateComplementDialog } from '@/components/produtos/CreateComplementDialog';
import { EditItemSheet, type EditTarget } from '@/components/produtos/EditItemSheet';
import { ComplementCategoriesDialog } from '@/components/produtos/ComplementCategoriesDialog';
import { SortableList } from '@/components/common/SortableList';
import { DeleteConfirmDialog } from '@/components/produtos/DeleteConfirmDialog';

const Produtos = () => {
  const catalog = useProducts();
  const { products, complementCategories, groupLibrary, isLoading, isError, error } = catalog;

  const [filtro, setFiltro] = useState('');
  // Edição em massa: ids dos complementos marcados. Um Set porque a operação
  // que mais roda é "está marcado?", uma vez por linha em cada render.
  const [selecionados, setSelecionados] = useState<Set<string>>(new Set());
  const [showNewProduct, setShowNewProduct] = useState(false);
  const [newGroupProduct, setNewGroupProduct] = useState<{ id: string; name: string } | null>(null);
  const [newComplementGroupId, setNewComplementGroupId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
  const [showCategories, setShowCategories] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);

  // Buscar sabor pelo nome. A lista de sabores é uma só e é longa (31 na Mi
  // Piace): sem busca, achar "pistache" no celular é rolagem. Produto e
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
          const id = complement.category_id;
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
    <Page className="space-y-6">
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
        <SortableList
          items={visiveis}
          onReorder={catalog.reorderProducts}
          disabled={Boolean(termo)}
          className="space-y-6"
        >
          {(product, dragHandle) => (
            <ProductCard
              product={product}
              catalog={catalog}
              categories={complementCategories}
              dragHandle={!termo ? dragHandle : undefined}
              filtro={termo}
              selecionados={selecionados}
              onToggleSelecao={alternarSelecao}
              onSelecionarGrupo={selecionarGrupo}
              onEdit={setEditTarget}
              onDelete={setDeleteTarget}
              onNewGroup={setNewGroupProduct}
              onNewComplement={setNewComplementGroupId}
            />
          )}
        </SortableList>
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
        library={groupLibrary}
        usedGroupIds={
          products
            .find((p) => p.id === newGroupProduct?.id)
            ?.groups.map((g) => g.group_id) ?? []
        }
        onCreate={catalog.createGroup}
      />
      <CreateComplementDialog
        open={!!newComplementGroupId}
        onOpenChange={(open) => !open && setNewComplementGroupId(null)}
        groupId={newComplementGroupId ?? ''}
        categories={complementCategories}
        onCreate={catalog.createComplement}
      />
      <ComplementCategoriesDialog
        open={showCategories}
        onOpenChange={setShowCategories}
        categories={complementCategories}
        usageByCategory={usoDasCategorias}
        onCreate={catalog.createComplementCategory}
        onRename={(id, data) => catalog.editItem('category', id, data)}
        onReorder={catalog.reorderCategories}
        onDelete={(id, name, usage) =>
          setDeleteTarget({
            entity: 'category',
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
        categories={complementCategories}
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
    </Page>
  );
};

export default Produtos;
