/**
 * Pedidos do Kanban: leitura com poll curto e mudança de status otimista.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { fetchOrders, updateOrderStatus } from '@/lib/api';
import { toOrder } from '@/lib/transforms';
import type { ApiOrder, OrderStatus } from '@/types/order';

export const ORDERS_QUERY_KEY = ['orders'] as const;

export function useOrders() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ORDERS_QUERY_KEY,
    queryFn: () => fetchOrders({ limit: 100 }),
    select: (data) => (data ?? []).map(toOrder),
    refetchInterval: 15000,
  });

  const mutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: OrderStatus }) =>
      updateOrderStatus(id, status),

    // Atualização otimista: o card muda de coluna na hora, sem esperar o servidor.
    onMutate: async ({ id, status }) => {
      await queryClient.cancelQueries({ queryKey: ORDERS_QUERY_KEY });
      const previous = queryClient.getQueryData<ApiOrder[]>(ORDERS_QUERY_KEY);
      queryClient.setQueryData<ApiOrder[]>(ORDERS_QUERY_KEY, (old) =>
        old?.map((order) => (order.id === id ? { ...order, status } : order)),
      );
      return { previous };
    },
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(ORDERS_QUERY_KEY, context.previous);
      toast.error('Não foi possível mover o pedido', {
        description: error instanceof Error ? error.message : undefined,
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
    isChangingStatus: mutation.isPending,
  };
}
