/**
 * Cliente HTTP do backend.
 *
 * Única porta de saída do front. Duas regras aqui:
 *  - a URL base vem do ambiente (`VITE_API_BASE_URL`), nunca hardcoded;
 *  - toda rota `/api/*` é administrativa e exige o header `X-API-Key`.
 */

import { API_BASE_URL, ADMIN_API_KEY } from './config';
import type {
  Complement,
  ComplementGroup,
  ComplementInput,
  ComplementCategoryInput,
  ComplementCategory,
  GroupInput,
  GroupLibraryEntry,
  Product,
  ProductInput,
  ProductListResponse,
  ReorderKind,
} from '@/types/catalog';
import type { Order, OrderStatus } from '@/types/order';
import type {
  DailySales,
  HourlySales,
  MetricsRange,
  MetricsSummary,
  ProductSales,
} from '@/types/metrics';
import type { Conversation, ConversationMessage } from '@/types/conversation';

/** Erro de API que carrega o status HTTP, para a UI decidir o que dizer. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function fallbackMessageForStatus(status: number): string {
  switch (status) {
    case 0:
      return 'Não foi possível falar com o servidor. Ele está no ar?';
    case 401:
    case 403:
      return 'Chave de acesso inválida. Confira VITE_ADMIN_API_KEY no .env do front.';
    case 404:
      return 'Recurso não encontrado.';
    case 409:
      return 'A operação conflita com o estado atual do registro.';
    case 500:
      return 'Erro interno do servidor.';
    default:
      return `Falha na requisição (HTTP ${status}).`;
  }
}

/**
 * Extrai a mensagem útil do corpo de erro do FastAPI.
 *
 * O FastAPI responde `{"detail": "texto"}` nos erros de negócio e
 * `{"detail": [{loc, msg, ...}]}` nos erros de validação do Pydantic — vale a
 * pena tratar os dois, senão o lojista só enxerga "Erro 422".
 */
export function extractErrorMessage(payload: unknown, status: number): string {
  if (typeof payload === 'string' && payload.trim()) return payload.trim();

  if (payload && typeof payload === 'object') {
    const record = payload as { detail?: unknown; message?: unknown };
    const detail = record.detail ?? record.message;

    if (typeof detail === 'string' && detail.trim()) return detail.trim();

    if (Array.isArray(detail)) {
      const parts = detail
        .map((entry) => {
          if (typeof entry === 'string') return entry;
          if (entry && typeof entry === 'object') {
            const { msg, loc } = entry as { msg?: unknown; loc?: unknown };
            const field = Array.isArray(loc)
              ? loc.filter((part) => part !== 'body').join('.')
              : '';
            if (typeof msg === 'string') return field ? `${field}: ${msg}` : msg;
          }
          return '';
        })
        .filter(Boolean);
      if (parts.length) return parts.join('; ');
    }
  }

  return fallbackMessageForStatus(status);
}

/**
 * A mensagem de um erro capturado, para a descrição do toast.
 *
 * Os três hooks de mutação escreviam `error instanceof Error ? ... : undefined`
 * cada um por conta. `undefined` é proposital: o toast já tem título, e um
 * segundo texto genérico embaixo só rouba espaço.
 */
export function errorDescription(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}

type QueryValue = string | number | boolean | undefined | null;

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return `${API_BASE_URL}${path}${qs ? `?${qs}` : ''}`;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal } = options;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      signal,
      headers: {
        'Content-Type': 'application/json',
        // Toda rota /api é administrativa: sem a chave o backend devolve 401.
        'X-API-Key': ADMIN_API_KEY,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // Falha de rede/CORS: o fetch rejeita sem status HTTP nenhum.
    throw new ApiError(fallbackMessageForStatus(0), 0);
  }

  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw new ApiError(extractErrorMessage(payload, response.status), response.status);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

/**
 * O contrato ora devolve `{chave: [...]}`, ora a lista pura. Em vez de quebrar
 * a tela quando o backend muda de formato, normalizamos num ponto só.
 */
export function unwrapList<T>(payload: unknown, key: string): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    if (Array.isArray(record[key])) return record[key] as T[];
    if (Array.isArray(record.items)) return record.items as T[];
  }
  return [];
}

// ============================================================================
// Catálogo — /api/products, /api/groups, /api/complements
// ============================================================================

/** Garante `groups`/`complements` presentes mesmo se o backend omitir os vazios. */
function normalizeProduct(product: Product): Product {
  return {
    ...product,
    groups: (product.groups ?? []).map((group) => ({
      ...group,
      complements: group.complements ?? [],
    })),
  };
}

export async function fetchProducts(): Promise<Product[]> {
  const data = await request<ProductListResponse | Product[]>('/api/products');
  return unwrapList<Product>(data, 'products').map(normalizeProduct);
}

export function createProduct(data: ProductInput): Promise<Product> {
  return request<Product>('/api/products', { method: 'POST', body: data });
}

export function updateProduct(id: string, data: Partial<ProductInput>): Promise<Product> {
  return request<Product>(`/api/products/${id}`, { method: 'PATCH', body: data });
}

export function deleteProduct(id: string): Promise<void> {
  return request<void>(`/api/products/${id}`, { method: 'DELETE' });
}

/**
 * Categorias de complemento ("Sem lactose", "Frutados", "Vegetariano"...).
 *
 * São dado do lojista, não constante do sistema: cada loja classifica os
 * complementos do seu jeito, e é por elas que o agente responde "tem opção sem
 * lactose?" e monta o cardápio agrupado que manda no WhatsApp.
 */
export async function fetchComplementCategories(): Promise<ComplementCategory[]> {
  const data = await request<ComplementCategory[]>('/api/complement-categories');
  return unwrapList<ComplementCategory>(data, 'complement_categories');
}

export function createComplementCategory(data: ComplementCategoryInput): Promise<ComplementCategory> {
  return request<ComplementCategory>('/api/complement-categories', { method: 'POST', body: data });
}

export function updateComplementCategory(
  id: string,
  data: Partial<ComplementCategoryInput>,
): Promise<ComplementCategory> {
  return request<ComplementCategory>(`/api/complement-categories/${id}`, {
    method: 'PATCH',
    body: data,
  });
}

/**
 * Grava a ordem em que o lojista arrastou os itens de uma lista.
 *
 * Uma requisição para a lista inteira: a ordem é uma coisa só, e um PATCH por
 * item deixaria o cardápio meio ordenado se um deles falhasse.
 */
export function reorderCatalog(kind: ReorderKind, ids: string[]): Promise<void> {
  return request<void>('/api/catalog/reorder', { method: 'POST', body: { kind, ids } });
}

export function deleteComplementCategory(id: string): Promise<void> {
  return request<void>(`/api/complement-categories/${id}`, { method: 'DELETE' });
}

/** A biblioteca de grupos — é dela que sai o "usar um grupo que já existe". */
export function listGroups(): Promise<GroupLibraryEntry[]> {
  return request<GroupLibraryEntry[]>('/api/groups').then((groups) => groups ?? []);
}

export function createGroup(productId: string, data: GroupInput): Promise<ComplementGroup> {
  return request<ComplementGroup>(`/api/products/${productId}/groups`, {
    method: 'POST',
    body: data,
  });
}

/**
 * Edita o grupo deste produto: a regra de escolha (do vínculo) e/ou o nome (da
 * lista compartilhada). `id` é o do vínculo — o mesmo que vem em `group.id`.
 */
export function updateGroup(id: string, data: Partial<GroupInput>): Promise<ComplementGroup> {
  return request<ComplementGroup>(`/api/product-groups/${id}`, { method: 'PATCH', body: data });
}

/**
 * Tira o grupo DESTE produto. A lista continua existindo para os outros — quem
 * apaga a lista inteira é `DELETE /api/groups/{group_id}`, que o painel não
 * expõe porque apagaria os sabores de todos os produtos de uma vez.
 */
export function deleteGroup(id: string): Promise<void> {
  return request<void>(`/api/product-groups/${id}`, { method: 'DELETE' });
}

export function createComplement(groupId: string, data: ComplementInput): Promise<Complement> {
  return request<Complement>(`/api/groups/${groupId}/complements`, {
    method: 'POST',
    body: data,
  });
}

export function updateComplement(id: string, data: Partial<ComplementInput>): Promise<Complement> {
  return request<Complement>(`/api/complements/${id}`, { method: 'PATCH', body: data });
}

export function deleteComplement(id: string): Promise<void> {
  return request<void>(`/api/complements/${id}`, { method: 'DELETE' });
}

// ============================================================================
// Pedidos — /api/orders
// ============================================================================

export async function fetchOrders(params?: {
  status?: OrderStatus;
  limit?: number;
}): Promise<Order[]> {
  const data = await request<Order[] | { orders: Order[] }>('/api/orders', {
    query: { status: params?.status, limit: params?.limit },
  });
  return unwrapList<Order>(data, 'orders');
}

export function updateOrderStatus(id: string, status: OrderStatus): Promise<Order> {
  return request<Order>(`/api/orders/${id}/status`, {
    method: 'PATCH',
    body: { status },
  });
}

// ============================================================================
// Métricas — /api/metrics/*
// ============================================================================

export function fetchMetricsSummary(range: MetricsRange): Promise<MetricsSummary> {
  return request<MetricsSummary>('/api/metrics/summary', { query: { range } });
}

export async function fetchDailySales(days: number, range?: MetricsRange): Promise<DailySales[]> {
  const data = await request<DailySales[]>('/api/metrics/daily-sales', {
    query: { days, range },
  });
  return unwrapList<DailySales>(data, 'daily_sales');
}

export async function fetchProductSales(range?: MetricsRange): Promise<ProductSales[]> {
  const data = await request<ProductSales[]>('/api/metrics/product-sales', { query: { range } });
  return unwrapList<ProductSales>(data, 'product_sales');
}

export async function fetchHourlySales(range?: MetricsRange): Promise<HourlySales[]> {
  const data = await request<HourlySales[]>('/api/metrics/hourly-sales', { query: { range } });
  return unwrapList<HourlySales>(data, 'hourly_sales');
}

// ============================================================================
// Conversas do agente — /api/conversations
// ============================================================================

export async function fetchConversations(): Promise<Conversation[]> {
  const data = await request<Conversation[] | { conversations: Conversation[] }>(
    '/api/conversations',
  );
  return unwrapList<Conversation>(data, 'conversations');
}

export async function fetchConversationMessages(id: string): Promise<ConversationMessage[]> {
  const data = await request<ConversationMessage[] | { messages: ConversationMessage[] }>(
    `/api/conversations/${id}/messages`,
  );
  return unwrapList<ConversationMessage>(data, 'messages');
}

/** Pausa (`true`) ou devolve (`false`) a conversa para o bot. */
export function setConversationHandoff(id: string, handoff: boolean): Promise<Conversation> {
  return request<Conversation>(`/api/conversations/${id}/handoff`, {
    method: 'POST',
    body: { handoff },
  });
}
