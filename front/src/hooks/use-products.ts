/**
 * Catálogo: produto > grupo > complementos.
 *
 * O `GET /api/products` já devolve a árvore aninhada, então o cache guarda uma
 * lista só e as mutações mexem nessa árvore de forma otimista — o lojista vê o
 * switch virar na hora e a linha some na hora, com rollback se o servidor negar.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  createComplement,
  createGroup,
  createProduct,
  deleteComplement,
  deleteGroup,
  deleteProduct,
  fetchProducts,
  updateComplement,
  updateGroup,
  updateProduct,
} from '@/lib/api';
import type {
  CatalogEntity,
  Complement,
  ComplementInput,
  GroupInput,
  Product,
  ProductInput,
} from '@/types/catalog';

export const PRODUCTS_QUERY_KEY = ['products'] as const;

function describe(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}

/** Aplica uma função em todos os complementos da árvore. */
function mapComplements(
  products: Product[],
  fn: (complement: Complement) => Complement,
): Product[] {
  return products.map((product) => ({
    ...product,
    groups: product.groups.map((group) => ({
      ...group,
      complements: group.complements.map(fn),
    })),
  }));
}

export function useProducts() {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });

  const query = useQuery({
    queryKey: PRODUCTS_QUERY_KEY,
    queryFn: fetchProducts,
  });

  const products = query.data ?? [];

  /** Escreve no cache e devolve o snapshot anterior para o rollback. */
  const patchCache = async (updater: (old: Product[]) => Product[]) => {
    await queryClient.cancelQueries({ queryKey: PRODUCTS_QUERY_KEY });
    const previous = queryClient.getQueryData<Product[]>(PRODUCTS_QUERY_KEY);
    queryClient.setQueryData<Product[]>(PRODUCTS_QUERY_KEY, (old) => updater(old ?? []));
    return { previous };
  };

  const rollback = (context: { previous?: Product[] } | undefined) => {
    if (context?.previous) queryClient.setQueryData(PRODUCTS_QUERY_KEY, context.previous);
  };

  // --- Disponibilidade (otimista) ------------------------------------------
  const toggleMutation = useMutation({
    mutationFn: ({
      entity,
      id,
      is_available,
    }: {
      entity: 'product' | 'complement';
      id: string;
      is_available: boolean;
    }) =>
      entity === 'product'
        ? updateProduct(id, { is_available })
        : updateComplement(id, { is_available }),
    onMutate: ({ entity, id, is_available }) =>
      patchCache((old) =>
        entity === 'product'
          ? old.map((p) => (p.id === id ? { ...p, is_available } : p))
          : mapComplements(old, (c) => (c.id === id ? { ...c, is_available } : c)),
      ),
    onError: (error, _vars, context) => {
      rollback(context);
      toast.error('Erro ao atualizar disponibilidade', { description: describe(error) });
    },
    onSettled: invalidate,
  });

  // --- Edição de nome/preço -------------------------------------------------
  const editMutation = useMutation({
    mutationFn: ({
      entity,
      id,
      data,
    }: {
      entity: CatalogEntity;
      id: string;
      data: Record<string, unknown>;
    }) => {
      if (entity === 'product') return updateProduct(id, data as Partial<ProductInput>);
      if (entity === 'group') return updateGroup(id, data as Partial<GroupInput>);
      return updateComplement(id, data as Partial<ComplementInput>);
    },
    onSuccess: () => {
      toast.success('Item atualizado');
      invalidate();
    },
    onError: (error) => toast.error('Erro ao atualizar o item', { description: describe(error) }),
  });

  // --- Criação --------------------------------------------------------------
  const createProductMutation = useMutation({
    mutationFn: createProduct,
    onSuccess: () => {
      toast.success('Produto criado');
      invalidate();
    },
    onError: (error) => toast.error('Erro ao criar o produto', { description: describe(error) }),
  });

  const createGroupMutation = useMutation({
    mutationFn: ({ productId, data }: { productId: string; data: GroupInput }) =>
      createGroup(productId, data),
    onSuccess: () => {
      toast.success('Categoria criada');
      invalidate();
    },
    onError: (error) => toast.error('Erro ao criar a categoria', { description: describe(error) }),
  });

  const createComplementMutation = useMutation({
    mutationFn: ({ groupId, data }: { groupId: string; data: ComplementInput }) =>
      createComplement(groupId, data),
    onSuccess: () => {
      toast.success('Complemento criado');
      invalidate();
    },
    onError: (error) =>
      toast.error('Erro ao criar o complemento', { description: describe(error) }),
  });

  // --- Exclusão em cascata (otimista) --------------------------------------
  const deleteMutation = useMutation({
    mutationFn: ({ entity, id }: { entity: CatalogEntity; id: string }) => {
      if (entity === 'product') return deleteProduct(id);
      if (entity === 'group') return deleteGroup(id);
      return deleteComplement(id);
    },
    onMutate: ({ entity, id }) =>
      patchCache((old) => {
        if (entity === 'product') return old.filter((p) => p.id !== id);
        if (entity === 'group') {
          return old.map((p) => ({ ...p, groups: p.groups.filter((g) => g.id !== id) }));
        }
        return old.map((p) => ({
          ...p,
          groups: p.groups.map((g) => ({
            ...g,
            complements: g.complements.filter((c) => c.id !== id),
          })),
        }));
      }),
    onError: (error, _vars, context) => {
      rollback(context);
      toast.error('Erro ao excluir', { description: describe(error) });
    },
    onSuccess: () => toast.success('Item excluído'),
    onSettled: invalidate,
  });

  return {
    products,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,

    toggleAvailability: (entity: 'product' | 'complement', id: string, is_available: boolean) =>
      toggleMutation.mutate({ entity, id, is_available }),

    editItem: (entity: CatalogEntity, id: string, data: Record<string, unknown>) =>
      editMutation.mutateAsync({ entity, id, data }),

    createProduct: (data: ProductInput) => createProductMutation.mutateAsync(data),

    createGroup: (productId: string, data: GroupInput) =>
      createGroupMutation.mutateAsync({ productId, data }),

    createComplement: (groupId: string, data: ComplementInput) =>
      createComplementMutation.mutateAsync({ groupId, data }),

    deleteItem: (entity: CatalogEntity, id: string) => deleteMutation.mutate({ entity, id }),

    isSaving:
      toggleMutation.isPending || editMutation.isPending || deleteMutation.isPending,
  };
}
