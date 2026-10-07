/**
 * Os hooks que buscam e gravam dados (react-query).
 *
 * As telas nao chamam `api.ts` direto: chamam um hook daqui, que cuida de
 * cache, recarregamento e do aviso na tela quando algo falha.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createComplement, createComplementCategory, createGroup, createOrder, createProduct, deleteComplement, deleteComplementCategory, deleteGroup, deleteProduct, fetchComplementCategories, errorDescription as describe, fetchProducts, listGroups, reorderCatalog, updateComplement, updateComplementCategory, updateGroup, updateProduct, errorDescription, fetchOrders, updateOrderStatus, fetchConversationMessages, fetchConversations, setConversationHandoff, fetchDailySales, fetchHourlySales, fetchMetricsSummary, fetchProductSales } from '@/api';
import type { CatalogEntity, Complement, ComplementInput, ComplementCategoryInput, GroupInput, GroupLibraryEntry, Product, ProductInput, ReorderKind } from '@/tipos';
import { toOrder, RANGE_TO_DAYS, toHourlyPoints, toProductPoints, toSalesPoints } from '@/formato';
import type { Order, OrderCreateInput, OrderStatus } from '@/tipos';
import { toMillis } from '@/formato';
import type { Conversation } from '@/tipos';
import type { MetricsRange } from '@/tipos';
import { tocarNotificacaoDePedidoNovo } from '@/som';
import { printOrder, PrinterError } from '@/impressora';
import { PRINTER_IP } from '@/api';

// ---------------------------------------------------------------
// use-async-submit
// ---------------------------------------------------------------

export function useAsyncSubmit() {
  const [loading, setLoading] = useState(false);

  const run = async (action: () => Promise<unknown>) => {
    setLoading(true);
    try {
      await action();
    } catch {
      // Erro já vira toast no hook de dados; aqui só liberamos o botão.
    } finally {
      setLoading(false);
    }
  };

  return { loading, run };
}

// ---------------------------------------------------------------
// use-products
// ---------------------------------------------------------------

export const PRODUCTS_QUERY_KEY = ['products'] as const;
const CATEGORIES_QUERY_KEY = ['complement-categories'] as const;
const GROUPS_QUERY_KEY = ['complement-groups'] as const;

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

  // Lista curta, mas não imutável: o lojista cria e renomeia categoria pelo
  // painel, então ela é recarregada junto com o resto quando muda.
  const categoriesQuery = useQuery({
    queryKey: CATEGORIES_QUERY_KEY,
    queryFn: fetchComplementCategories,
  });

  // A biblioteca de grupos: é ela que permite um produto novo reaproveitar a
  // lista de sabores que já existe, em vez de ganhar uma cópia só dele.
  const groupsQuery = useQuery({
    queryKey: GROUPS_QUERY_KEY,
    queryFn: listGroups,
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
    }): Promise<unknown> =>
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
      if (entity === 'category') {
        return updateComplementCategory(id, data as Partial<ComplementCategoryInput>);
      }
      return updateComplement(id, data as Partial<ComplementInput>);
    },
    onSuccess: () => {
      toast.success('Item atualizado');
      invalidate();
      queryClient.invalidateQueries({ queryKey: CATEGORIES_QUERY_KEY });
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
      toast.success('Grupo adicionado ao produto');
      invalidate();
      queryClient.invalidateQueries({ queryKey: GROUPS_QUERY_KEY });
    },
    onError: (error) => toast.error('Erro ao criar o grupo', { description: describe(error) }),
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
      if (entity === 'category') return deleteComplementCategory(id);
      return deleteComplement(id);
    },
    onMutate: ({ entity, id }) =>
      patchCache((old) => {
        // Apagar categoria não mexe na árvore de produtos: o vínculo do sabor
        // vira nulo no banco (ON DELETE SET NULL) e o sabor continua lá.
        if (entity === 'category') return old;
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
    onSettled: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: CATEGORIES_QUERY_KEY });
    },
  });

  // --- Ordem (arrastar e soltar) -------------------------------------------
  // Otimista de propósito: quem arrastou já viu o item no lugar novo, e uma
  // lista que "pula de volta" por meio segundo até o servidor responder passa
  // a impressão de que o arrasto não pegou.
  const reorderMutation = useMutation({
    mutationFn: ({ kind, ids }: { kind: ReorderKind; ids: string[] }) =>
      reorderCatalog(kind, ids),
    onError: (error, _vars, context) => {
      rollback(context as { previous?: Product[] } | undefined);
      toast.error('Não consegui salvar a ordem', { description: describe(error) });
    },
    onSettled: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: CATEGORIES_QUERY_KEY });
    },
  });

  /** Reordena a lista no cache antes de mandar, pela ordem de ids recebida. */
  const ordenarPorIds = <T extends { id: string }>(lista: T[], ids: string[]): T[] => {
    const posicao = new Map(ids.map((id, i) => [id, i]));
    return [...lista].sort(
      (a, b) => (posicao.get(a.id) ?? 0) - (posicao.get(b.id) ?? 0),
    );
  };

  // --- Categorias de complemento --------------------------------------------
  const createCategoryMutation = useMutation({
    mutationFn: createComplementCategory,
    onSuccess: () => {
      toast.success('Categoria criada');
      queryClient.invalidateQueries({ queryKey: CATEGORIES_QUERY_KEY });
    },
    onError: (error) =>
      toast.error('Erro ao criar a categoria', { description: describe(error) }),
  });

  return {
    products,
    complementCategories: categoriesQuery.data ?? [],
    groupLibrary: (groupsQuery.data ?? []) as GroupLibraryEntry[],
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

    createComplementCategory: (data: ComplementCategoryInput) =>
      createCategoryMutation.mutateAsync(data),

    reorderProducts: async (ids: string[]) => {
      const context = await patchCache((old) => ordenarPorIds(old, ids));
      reorderMutation.mutate({ kind: 'product', ids }, { onError: () => rollback(context) });
    },

    reorderGroups: async (productId: string, ids: string[]) => {
      const context = await patchCache((old) =>
        old.map((p) =>
          p.id === productId ? { ...p, groups: ordenarPorIds(p.groups, ids) } : p,
        ),
      );
      reorderMutation.mutate(
        { kind: 'product_group', ids },
        { onError: () => rollback(context) },
      );
    },

    /**
     * `linkId` é o grupo como aquele produto o vê; a lista, porém, é
     * compartilhada, então a nova ordem vale para todo produto que a usa — e o
     * cache precisa mostrar isso na hora, senão a tela mente até o refetch.
     */
    reorderComplements: async (linkId: string, ids: string[]) => {
      const sharedId = products
        .flatMap((p) => p.groups)
        .find((g) => g.id === linkId)?.group_id;
      const context = await patchCache((old) =>
        old.map((p) => ({
          ...p,
          groups: p.groups.map((g) =>
            g.group_id === sharedId ? { ...g, complements: ordenarPorIds(g.complements, ids) } : g,
          ),
        })),
      );
      reorderMutation.mutate({ kind: 'complement', ids }, { onError: () => rollback(context) });
    },

    reorderCategories: (ids: string[]) => reorderMutation.mutate({ kind: 'category', ids }),

    deleteItem: (entity: CatalogEntity, id: string) => deleteMutation.mutate({ entity, id }),

    isSaving:
      toggleMutation.isPending || editMutation.isPending || deleteMutation.isPending,
  };
}

// ---------------------------------------------------------------
// use-orders
// ---------------------------------------------------------------

export const ORDERS_QUERY_KEY = ['orders'] as const;

export function useOrders() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ORDERS_QUERY_KEY,
    queryFn: () => fetchOrders({ limit: 100 }),
    select: (data) => (data ?? []).map(toOrder),
    refetchInterval: 15000,
  });

  // Toca um som e manda a ficha pra impressora quando um pedido "nasce" pro
  // balcão — ou seja, deixa de ser `novo` (Pix pendente) ou já chega direto
  // em `preparando` (lançamento manual). `null` no ref é "ainda não carregou
  // a primeira vez"; sem essa distinção, TODO pedido já existente tocava o
  // som de novo só por o painel ter sido aberto/recarregado.
  const idsConhecidos = useRef<Set<string> | null>(null);

  useEffect(() => {
    const orders = query.data ?? [];
    const acionaveis = orders.filter((order) => order.status !== 'novo');

    if (idsConhecidos.current === null) {
      idsConhecidos.current = new Set(acionaveis.map((order) => order.id));
      return;
    }

    const vistos = idsConhecidos.current;
    const novos = acionaveis.filter((order) => !vistos.has(order.id));
    if (novos.length === 0) return;

    for (const order of novos) vistos.add(order.id);
    tocarNotificacaoDePedidoNovo();

    if (PRINTER_IP) {
      for (const order of novos) {
        printOrder(order).catch((error: unknown) => {
          toast.error(`Não consegui imprimir a ficha do pedido ${order.code}`, {
            description: error instanceof PrinterError ? error.message : undefined,
          });
        });
      }
    }
  }, [query.data]);

  const createMutation = useMutation({
    mutationFn: (data: OrderCreateInput) => createOrder(data),
    onSuccess: () => {
      toast.success('Pedido registrado');
      queryClient.invalidateQueries({ queryKey: ORDERS_QUERY_KEY });
    },
    onError: (error) => {
      toast.error('Não foi possível registrar o pedido', { description: errorDescription(error) });
    },
  });

  const mutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: OrderStatus }) =>
      updateOrderStatus(id, status),

    // Atualização otimista: o card muda de coluna na hora, sem esperar o servidor.
    onMutate: async ({ id, status }) => {
      await queryClient.cancelQueries({ queryKey: ORDERS_QUERY_KEY });
      const previous = queryClient.getQueryData<Order[]>(ORDERS_QUERY_KEY);
      queryClient.setQueryData<Order[]>(ORDERS_QUERY_KEY, (old) =>
        old?.map((order) => (order.id === id ? { ...order, status } : order)),
      );
      return { previous };
    },
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(ORDERS_QUERY_KEY, context.previous);
      toast.error('Não foi possível mover o pedido', {
        description: errorDescription(error),
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ORDERS_QUERY_KEY });
    },
  });

  return {
    orders: query.data ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
    changeStatus: (id: string, status: OrderStatus) => mutation.mutate({ id, status }),
    createManualOrder: (data: OrderCreateInput) => createMutation.mutateAsync(data),
    isCreatingOrder: createMutation.isPending,
  };
}

// ---------------------------------------------------------------
// use-conversations
// ---------------------------------------------------------------

const POLL_INTERVAL = 10_000;

export const CONVERSATIONS_QUERY_KEY = ['conversations'] as const;

export function useConversations() {
  return useQuery({
    queryKey: CONVERSATIONS_QUERY_KEY,
    queryFn: fetchConversations,
    refetchInterval: POLL_INTERVAL,
    // Mais recente primeiro; conversa sem mensagem vai para o fim.
    select: (rows) =>
      [...(rows ?? [])].sort(
        (a, b) => toMillis(b.last_message_at) - toMillis(a.last_message_at),
      ),
  });
}

export function useConversationMessages(conversationId: string | null) {
  return useQuery({
    queryKey: ['conversations', conversationId, 'messages'],
    queryFn: () => fetchConversationMessages(conversationId as string),
    enabled: Boolean(conversationId),
    refetchInterval: POLL_INTERVAL,
  });
}

/** "Assumir atendimento" (handoff=true) e "devolver ao bot" (handoff=false). */
export function useHandoffMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, handoff }: { id: string; handoff: boolean }) =>
      setConversationHandoff(id, handoff),
    onMutate: async ({ id, handoff }) => {
      await queryClient.cancelQueries({ queryKey: CONVERSATIONS_QUERY_KEY });
      const previous = queryClient.getQueryData<Conversation[]>(CONVERSATIONS_QUERY_KEY);
      queryClient.setQueryData<Conversation[]>(CONVERSATIONS_QUERY_KEY, (old) =>
        old?.map((conversation) =>
          conversation.id === id ? { ...conversation, handoff } : conversation,
        ),
      );
      return { previous };
    },
    onSuccess: (_data, { handoff }) => {
      toast.success(handoff ? 'Bot pausado nesta conversa' : 'Bot retomou o atendimento');
    },
    onError: (error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(CONVERSATIONS_QUERY_KEY, context.previous);
      }
      toast.error('Não foi possível alterar o atendimento', {
        description: errorDescription(error),
      });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: CONVERSATIONS_QUERY_KEY }),
  });
}

// ---------------------------------------------------------------
// use-metrics
// ---------------------------------------------------------------

const STALE_TIME = 30_000;

function useMetricsSummary(range: MetricsRange) {
  return useQuery({
    queryKey: ['metrics', 'summary', range],
    queryFn: () => fetchMetricsSummary(range),
    staleTime: STALE_TIME,
  });
}

function useDailySales(range: MetricsRange) {
  return useQuery({
    queryKey: ['metrics', 'daily-sales', range],
    queryFn: () => fetchDailySales(RANGE_TO_DAYS[range], range),
    select: toSalesPoints,
    staleTime: STALE_TIME,
  });
}

function useProductSales(range: MetricsRange) {
  return useQuery({
    queryKey: ['metrics', 'product-sales', range],
    queryFn: () => fetchProductSales(range),
    select: (rows) => toProductPoints(rows),
    staleTime: STALE_TIME,
  });
}

function useHourlySales(range: MetricsRange) {
  return useQuery({
    queryKey: ['metrics', 'hourly-sales', range],
    queryFn: () => fetchHourlySales(range),
    select: toHourlyPoints,
    staleTime: STALE_TIME,
  });
}

/** Agrupa as quatro queries — o Admin só precisa de um objeto. */
export function useMetrics(range: MetricsRange) {
  const summary = useMetricsSummary(range);
  const daily = useDailySales(range);
  const products = useProductSales(range);
  const hourly = useHourlySales(range);

  return {
    summary,
    daily,
    products,
    hourly,
    /** Refaz tudo — usado pelo botão "tentar de novo". */
    refetchAll: () => {
      summary.refetch();
      daily.refetch();
      products.refetch();
      hourly.refetch();
    },
  };
}
